import os, sys, json, base64, threading, argparse
from datetime import datetime
import numpy as np
from flask import Flask, send_from_directory, request, jsonify
from flask_socketio import SocketIO, emit
from dotenv import load_dotenv
from openai import OpenAI
import websocket

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────────────
STUDY_DIR = os.path.dirname(os.path.abspath(__file__))
IMPL_DIR = os.path.join(os.path.dirname(STUDY_DIR), "Implementation")
sys.path.insert(0, IMPL_DIR)
sys.path.insert(0, os.path.join(IMPL_DIR, "director_agent"))
sys.path.insert(0, os.path.join(IMPL_DIR, "director_agent", "time_constrained"))
load_dotenv(os.path.join(IMPL_DIR, ".env"))

from director_core import get_director_decision
from time_director_core import get_time_director_decision
from time_control import TemporalMonitor
from character_prompts.olaf import CHARACTER as OLAF_CHARACTER
from scenarios.olaf_derailment_scenario_suite import NO_DERAILMENT_SCENARIOS
from audio_fx import get_fx_chain

# ── CLI args ───────────────────────────────────────────────────────────────────
# Condition A (default, port 3003): time-constrained Story B with pacing module ON
# Condition B (port 3004): Story B director-only, pacing module OFF — control group
parser = argparse.ArgumentParser(description="Olaf User Study Server")
parser.add_argument("--condition", default=os.getenv("STUDY_CONDITION", "A"),
                    choices=["A", "B"],
                    help="A = pacing ON (default), B = pacing OFF (control)")
parser.add_argument("--port", type=int, default=int(os.getenv("PORT", 3003)))
args = parser.parse_args()

STUDY_CONDITION = args.condition
PORT = args.port

print(f"[Study] Starting in condition {STUDY_CONDITION} on port {PORT}")

# ── Fixed study config ─────────────────────────────────────────────────────────
STORY_1_KEY = "olaf_once_upon_a_snowman_origin_no_derailment"
STORY_2_KEY = "olaf_retells_red_riding_hood_no_derailment"
STORY_2_TIME_LIMIT = 3.0  # minutes — same wall-clock limit for both conditions
AUTO_ADVANCE_SECONDS = 60  # inject neutral prompt if user is idle this long after their last input

_SCENARIO_REGISTRY = {sc["scenario_name"]: sc for sc in NO_DERAILMENT_SCENARIOS}

OLAF_AUDIOFX_CONFIG = {
    "pitch_shift": {"semitones": 2},
    "reverb": {"room_size": 0.25, "dry_level": 0.85, "wet_level": 0.15},
}


def apply_fx(pcm: bytes, fx_chain, sr: int = 24_000) -> bytes:
    if not fx_chain or not pcm:
        return pcm
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    return (np.clip(fx_chain(audio, sr), -1.0, 1.0) * 32767).astype(np.int16).tobytes()


# ── App ────────────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder="public")
app.config["SECRET_KEY"] = "olaf-study-2026"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

DIRECTOR_MODEL = "gpt-4o-mini"
REALTIME_MODEL = "gpt-realtime"
SR = 24_000

api_key = os.getenv("OPENAI_API_KEY")
_client = OpenAI(api_key=api_key)
olaf_fx = get_fx_chain(OLAF_AUDIOFX_CONFIG)

# ── Study-level state ──────────────────────────────────────────────────────────
_study_phase = 0           # 0=idle, 1=story1, 2=story2
_study_output: dict = {}   # accumulates full study data
_story_save_paths: dict = {}  # phase -> path of the transcript file written on story end

# ── Per-story runtime state ────────────────────────────────────────────────────
_state: dict = {
    "beat_index": 0, "completed_beats": [], "story_so_far": "",
    "turns_in_current_beat": 0, "expansion_index": 0,
    "beats": [], "story_topic": "", "scenario_name": "", "time_limit": 3.0,
}
_lock = threading.Lock()
_transcript: list = []
_monitor: TemporalMonitor | None = None
_openai_ws = None
_current_sid = None
_last_user_input = ""
_time_up_injected = False

# Auto-advance state
_auto_advance_timer: threading.Timer | None = None


def reset_story(scenario_key: str, phase: int, time_limit: float = 3.0):
    global _transcript, _monitor, _last_user_input, _time_up_injected, _auto_advance_timer
    sc = _SCENARIO_REGISTRY[scenario_key]
    with _lock:
        _state.update({
            "beats": sc["beats"], "story_topic": sc["story_topic"],
            "scenario_name": scenario_key, "beat_index": 0,
            "completed_beats": [], "story_so_far": "",
            "turns_in_current_beat": 0, "expansion_index": 0,
            "time_limit": time_limit,
        })
    _transcript = []
    _last_user_input = ""
    _time_up_injected = False
    _cancel_auto_advance()
    _monitor = None
    # Phase 2 always has a wall-clock timer; pacing is condition-dependent
    if phase == 2:
        if STUDY_CONDITION == "A":
            _monitor = TemporalMonitor(
                time_limit_minutes=time_limit,
                total_beats=len(sc["beats"]),
                final_buffer_seconds=30.0,
            )
        else:
            # Condition B: director-only, but still stop after time_limit minutes
            _monitor = None
            _start_condition_b_timer(time_limit)


def _start_condition_b_timer(time_limit_minutes: float):
    """Fire time_up after the wall-clock limit elapses (condition B control group)."""
    import time as _time
    _wall_start = _time.time()

    def _check():
        elapsed = _time.time() - _wall_start
        if _current_sid:
            socketio.emit("time_up", {}, room=_current_sid)
        threading.Thread(target=_auto_finish_story2, daemon=True).start()

    t = threading.Timer(time_limit_minutes * 60, _check)
    t.daemon = True
    t.start()
    # Store so we can cancel on reset
    global _monitor
    _monitor = None
    # Stash the timer reference via a module-level var
    global _cond_b_timer
    _cond_b_timer = t


_cond_b_timer: threading.Timer | None = None


def get_snap():
    with _lock:
        return dict(_state)


# ── System prompt ──────────────────────────────────────────────────────────────
def build_prompt(state: dict) -> str:
    beats = state["beats"]
    idx = state["beat_index"]
    si = min(idx, len(beats) - 1)
    cb = beats[si]
    nb = beats[si + 1]["name"] if si < len(beats) - 1 else "None"
    tail = state["story_so_far"][-600:] if state["story_so_far"] else "(story just started)"
    tl = state.get("time_limit", 3.0)

    time_line = f"\nThe story has a target duration of {tl} minutes.\n" if _study_phase == 2 and STUDY_CONDITION == "A" else ""
    pacing = """
## Pacing Rules (from pacing_mode in tool result)
- too_fast: ahead of schedule — expand beat. Use expansion_hint if present.
- normal: continue naturally.
- hurry: progress faster, avoid lingering.
- critical: compress, move toward ending quickly.
- final: time is up — close all remaining beats now in one response.
""" if _study_phase == 2 and STUDY_CONDITION == "A" else ""

    return f"""You are an interactive storytelling engine voicing Olaf the snowman.
You speak AS Olaf. Stay fully in character at all times.{time_line}
CRITICAL: Before EVERY response you MUST call the get_director_decision tool.
Do not speak until you have the director's instruction.

{OLAF_CHARACTER["character_prompt"]}

## Story Topic
{state["story_topic"]}

## Actor Rules
- Speak only as Olaf. Never mention the Director or the tool.
- Keep responses short: 2–4 sentences, natural spoken aloud.
- The director_instruction in the tool result is mandatory — realize it.
- Vary tone: sometimes excited, sometimes curious, sometimes gentle.
- Do not start most turns with "Oh". Do not repeat the same phrases.
{pacing}
## Current Story State
Beat {idx + 1} of {len(beats)}: {cb["name"]}
Goal: {cb["goal"]}
Next beat: {nb}
Completed: {json.dumps(state["completed_beats"])}

Story so far:
{tail}""".strip()


DIRECTOR_TOOL = {
    "type": "function",
    "name": "get_director_decision",
    "description": "Get the director's instruction for this story turn. Call BEFORE every response.",
    "parameters": {
        "type": "object",
        "properties": {"user_input": {"type": "string", "description": "What the user just said."}},
        "required": ["user_input"],
    },
}


# ── Auto-advance helpers ───────────────────────────────────────────────────────
def _cancel_auto_advance():
    global _auto_advance_timer
    if _auto_advance_timer:
        _auto_advance_timer.cancel()
        _auto_advance_timer = None


def _schedule_auto_advance():
    """After Olaf finishes a turn, schedule a neutral prompt if user stays silent."""
    _cancel_auto_advance()
    global _auto_advance_timer

    def _fire():
        if not _openai_ws or not _current_sid:
            return
        msg = "[The user is listening — continue the story naturally without waiting for a response]"
        with _lock:
            _state["story_so_far"] += f"\nUser: (no response)"
        try:
            _openai_ws.send(json.dumps({
                "type": "conversation.item.create",
                "item": {"type": "message", "role": "user",
                         "content": [{"type": "input_text", "text": msg}]},
            }))
            _openai_ws.send(json.dumps({"type": "response.create"}))
        except Exception as e:
            print(f"[auto-advance error] {e}")
            return
        # Reschedule so the director keeps being called if user stays silent.
        # This ensures pacing_mode="final" and the time-up injection are reached.
        _schedule_auto_advance()

    _auto_advance_timer = threading.Timer(AUTO_ADVANCE_SECONDS, _fire)
    _auto_advance_timer.daemon = True
    _auto_advance_timer.start()


# ── Director tool handler ──────────────────────────────────────────────────────
def handle_director_tool(ws, event: dict):
    global _last_user_input, _time_up_injected

    args = json.loads(event.get("arguments", "{}"))
    user_input = args.get("user_input") or _last_user_input or "(no input)"

    with _lock:
        _state["turns_in_current_beat"] += 1
        snap = dict(_state)

    beats = snap["beats"]
    si = min(snap["beat_index"], len(beats) - 1)
    cb = beats[si]
    nb = beats[si + 1]["name"] if si < len(beats) - 1 else "None"
    pacing_mode = "normal"
    temporal = {}

    # ── Phase 1: Standard Director ─────────────────────────────────────────────
    if _study_phase == 1:
        try:
            decision = get_director_decision(
                client=_client, model=DIRECTOR_MODEL,
                user_input=user_input, story_state=snap,
                character=OLAF_CHARACTER, story_topic=snap["story_topic"],
                beats=beats,
            )
        except Exception as e:
            print(f"[P1 director error] {e}")
            decision = {"director_instruction": "Continue the story naturally.", "decision_type": "progress_story"}

        if decision.get("should_complete_beat"):
            with _lock:
                idx = _state["beat_index"]
                if idx < len(beats):
                    _state["completed_beats"].append(beats[idx]["name"])
                    _state["beat_index"] += 1
                    _state["turns_in_current_beat"] = 0
                    print(f"[Beat → {_state['beat_index']}]")

        tool_result = {
            "director_instruction": decision.get("director_instruction", ""),
            "decision_type": decision.get("decision_type", "progress_story"),
            "current_beat": cb["name"], "current_beat_goal": cb["goal"], "next_beat": nb,
        }
        emit_data = {
            "decision_type": decision.get("decision_type"),
            "instruction": decision.get("director_instruction", "")[:80],
            "pacing_mode": "normal",
        }

    # ── Phase 2, Condition A: Time-Constrained Director ────────────────────────
    elif _study_phase == 2 and STUDY_CONDITION == "A":
        temporal = _monitor.state(si, beats) if _monitor else {
            "elapsed_seconds": 0, "remaining_seconds": snap["time_limit"] * 60,
            "pacing_mode": "normal",
        }
        pacing_mode = temporal.get("pacing_mode", "normal")

        try:
            decision = get_time_director_decision(
                client=_client, model=DIRECTOR_MODEL,
                user_input=user_input, story_state=snap,
                character=OLAF_CHARACTER, story_topic=snap["story_topic"],
                beats=beats, temporal_state=temporal,
            )
        except Exception as e:
            print(f"[P2A director error] {e}")
            decision = {"director_instruction": "Continue the story naturally.", "decision_type": "progress_story"}

        _imp = {"high": 0, "medium": 1, "low": 2}

        def beat_lines(from_idx):
            rem = sorted(beats[from_idx:], key=lambda b: _imp.get(b.get("importance", "medium"), 1))
            return [f"- {b['name']} [{b.get('importance','medium').upper()}]: {b['goal']}" for b in rem]

        suggested_exp = None
        if pacing_mode == "too_fast":
            decision["should_complete_beat"] = False
            exps = cb.get("expansions", [])
            ei = snap.get("expansion_index", 0)
            if ei < len(exps):
                suggested_exp = exps[ei]
                with _lock:
                    _state["expansion_index"] = ei + 1
                decision["director_instruction"] = f"Ahead of schedule — expand using: {suggested_exp}"
            else:
                decision["director_instruction"] = "Ahead of schedule — enrich with emotional depth or sensory detail."

        elif pacing_mode == "final":
            decision["should_complete_beat"] = True
            decision["decision_type"] = "close_story"
            decision["director_instruction"] = (
                "FINAL RESPONSE — close the story now. "
                "Cover ALL remaining beats. HIGH must be narrated, MEDIUM one sentence, LOW can skip.\n"
                + "\n".join(beat_lines(si))
            )
            # Mark time-up now so _auto_finish_story2 fires after this response
            # without waiting for a second director call past the 3-minute mark
            _time_up_injected = True
            if _current_sid:
                socketio.emit("time_up", {}, room=_current_sid)

        elif pacing_mode == "hurry":
            if snap.get("turns_in_current_beat", 0) >= 2:
                decision["should_complete_beat"] = True
                decision["director_instruction"] = (
                    decision.get("director_instruction", "") + " Wrap up this beat now and move on."
                )

        elif pacing_mode == "critical":
            decision["should_complete_beat"] = True
            next_high = next((b for b in beats[si + 1:] if b.get("importance") == "high"), None)
            if next_high:
                decision["director_instruction"] = (
                    decision.get("director_instruction", "") +
                    f" Bridge immediately to: {next_high['name']} — {next_high['goal']}"
                )

        if decision.get("should_complete_beat"):
            with _lock:
                idx = _state["beat_index"]
                if pacing_mode == "final":
                    for b in beats[idx:]:
                        _state["completed_beats"].append(b["name"])
                    _state["beat_index"] = len(beats)
                elif idx < len(beats):
                    _state["completed_beats"].append(beats[idx]["name"])
                    _state["beat_index"] += 1
                _state["turns_in_current_beat"] = 0
                _state["expansion_index"] = 0
                print(f"[Beat → {_state['beat_index']} | {pacing_mode}]")

        tool_result = {
            "director_instruction": decision.get("director_instruction", ""),
            "decision_type": decision.get("decision_type", "progress_story"),
            "pacing_mode": pacing_mode,
            "elapsed_seconds": temporal.get("elapsed_seconds", 0),
            "remaining_seconds": temporal.get("remaining_seconds", 0),
            "current_beat": cb["name"], "current_beat_goal": cb["goal"], "next_beat": nb,
            "story_so_far_tail": snap["story_so_far"][-300:],
        }
        if suggested_exp:
            tool_result["expansion_hint"] = suggested_exp

        emit_data = {
            "decision_type": decision.get("decision_type"),
            "instruction": decision.get("director_instruction", "")[:80],
            "pacing_mode": pacing_mode,
            "elapsed_seconds": temporal.get("elapsed_seconds", 0),
            "remaining_seconds": temporal.get("remaining_seconds", 0),
        }
        print(f"[P2A | {pacing_mode} | {temporal.get('remaining_seconds', 0):.0f}s] "
              f"{decision.get('director_instruction', '')[:60]}...")

    # ── Phase 2, Condition B: Standard Director (no pacing, wall-clock cut-off) ─
    elif _study_phase == 2 and STUDY_CONDITION == "B":
        try:
            decision = get_director_decision(
                client=_client, model=DIRECTOR_MODEL,
                user_input=user_input, story_state=snap,
                character=OLAF_CHARACTER, story_topic=snap["story_topic"],
                beats=beats,
            )
        except Exception as e:
            print(f"[P2B director error] {e}")
            decision = {"director_instruction": "Continue the story naturally.", "decision_type": "progress_story"}

        if decision.get("should_complete_beat"):
            with _lock:
                idx = _state["beat_index"]
                if idx < len(beats):
                    _state["completed_beats"].append(beats[idx]["name"])
                    _state["beat_index"] += 1
                    _state["turns_in_current_beat"] = 0
                    print(f"[Beat → {_state['beat_index']} | condB]")

        tool_result = {
            "director_instruction": decision.get("director_instruction", ""),
            "decision_type": decision.get("decision_type", "progress_story"),
            "pacing_mode": "normal",
            "elapsed_seconds": 0,
            "remaining_seconds": snap["time_limit"] * 60,
            "current_beat": cb["name"], "current_beat_goal": cb["goal"], "next_beat": nb,
        }
        emit_data = {
            "decision_type": decision.get("decision_type"),
            "instruction": decision.get("director_instruction", "")[:80],
            "pacing_mode": "normal",
            "elapsed_seconds": 0,
            "remaining_seconds": snap["time_limit"] * 60,
        }
        print(f"[P2B | condB] {decision.get('director_instruction', '')[:60]}...")

    else:
        return

    # ── Common: update session, emit, log, send tool result ───────────────────
    snap_now = get_snap()
    ws.send(json.dumps({
        "type": "session.update",
        "session": {"type": "realtime", "instructions": build_prompt(snap_now)},
    }))

    if _current_sid:
        socketio.emit("director_decision", emit_data, room=_current_sid)

    entry = {
        "turn": len(_transcript) + 1,
        "beat": cb["name"],
        "user_input": user_input,
        "director_decision": decision,
        "pacing_mode": pacing_mode,
        "character_response": "",
    }
    if _study_phase == 2 and temporal:
        entry["elapsed_seconds"] = temporal.get("elapsed_seconds", 0)
        entry["remaining_seconds"] = temporal.get("remaining_seconds", 0)
    _transcript.append(entry)

    ws.send(json.dumps({
        "type": "conversation.item.create",
        "item": {
            "type": "function_call_output",
            "call_id": event["call_id"],
            "output": json.dumps(tool_result),
        },
    }))
    ws.send(json.dumps({"type": "response.create"}))

    # Time-up injection for phase 2 condition A only (condition B uses wall timer)
    if (_study_phase == 2 and STUDY_CONDITION == "A" and _monitor
            and _monitor.should_stop_for_time() and not _time_up_injected):
        _time_up_injected = True
        if _current_sid:
            socketio.emit("time_up", {}, room=_current_sid)
        ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message", "role": "user",
                "content": [{"type": "input_text",
                             "text": "[Story time ended — wrap up all remaining beats with a complete, satisfying ending]"}],
            },
        }))
        ws.send(json.dumps({"type": "response.create"}))


def _auto_finish_story2():
    """Called in a background thread after Olaf's time-up wrap-up response finishes."""
    import time as _time
    _time.sleep(1.0)
    with _lock:
        snap = dict(_state)
    transcript_copy = list(_transcript)
    elapsed = 0
    if _monitor:
        try:
            elapsed = _monitor.elapsed_seconds()
        except Exception:
            pass
    story_data = {
        "scenario": snap.get("scenario_name", ""),
        "story_topic": snap.get("story_topic", ""),
        "study_condition": STUDY_CONDITION,
        "director_type": "time_constrained" if STUDY_CONDITION == "A" else "standard_cutoff",
        "beats_completed": snap["beat_index"],
        "completed_beats": snap["completed_beats"],
        "elapsed_seconds": round(elapsed, 2),
        "time_limit_minutes": STORY_2_TIME_LIMIT,
        "turns": transcript_copy,
    }
    _study_output["story_2"] = story_data
    print(f"[Study] Story 2 auto-saved after time-up ({len(transcript_copy)} turns)")
    if _current_sid:
        socketio.emit("story_finished", {"phase": 2, "turns": len(transcript_copy)}, room=_current_sid)
    close_ws()


# ── OpenAI Realtime WebSocket ──────────────────────────────────────────────────
def run_openai_ws():
    global _openai_ws

    def on_open(ws):
        state = get_snap()
        ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "type": "realtime",
                "instructions": build_prompt(state),
                "audio": {"output": {"voice": "verse"}},
                "tools": [DIRECTOR_TOOL],
                "tool_choice": "auto",
            },
        }))
        print(f"[WS] connected (phase {_study_phase}, condition {STUDY_CONDITION})")

    def on_message(ws, message):
        global _last_user_input
        try:
            data = json.loads(message)
        except Exception:
            return
        etype = data.get("type", "")

        if etype == "session.created":
            if _current_sid:
                socketio.emit("session_started",
                              {"phase": _study_phase, "condition": STUDY_CONDITION},
                              room=_current_sid)

        elif etype == "response.output_audio.delta":
            pcm = base64.b64decode(data["delta"])
            if olaf_fx:
                try:
                    pcm = apply_fx(pcm, olaf_fx, SR)
                except Exception:
                    pass
            if _current_sid:
                socketio.emit("audio_output", {"audio": base64.b64encode(pcm).decode()}, room=_current_sid)

        elif etype == "response.output_audio_transcript.delta":
            delta = data.get("delta", "")
            if delta and _current_sid:
                socketio.emit("transcript_assistant", {"delta": delta}, room=_current_sid)

        elif etype == "response.function_call_arguments.done":
            if data.get("name") == "get_director_decision":
                threading.Thread(target=handle_director_tool, args=(ws, data), daemon=True).start()

        elif etype == "response.done":
            olaf_text = ""
            try:
                for item in data.get("response", {}).get("output", []):
                    for part in item.get("content", []):
                        olaf_text += part.get("transcript") or part.get("text") or ""
            except Exception:
                pass
            if olaf_text and _transcript:
                _transcript[-1]["character_response"] = olaf_text
                with _lock:
                    _state["story_so_far"] += f"\nOlaf: {olaf_text}\n"
            if _current_sid:
                socketio.emit("response_done", {}, room=_current_sid)
            # Condition A: auto-finish after time-up wrap-up
            if _study_phase == 2 and STUDY_CONDITION == "A" and _time_up_injected and _current_sid:
                threading.Thread(target=_auto_finish_story2, daemon=True).start()

        elif etype == "error":
            print(f"[OpenAI error] {data}")
            if _current_sid:
                socketio.emit("error", {"message": str(data.get("error", data))}, room=_current_sid)

    def on_error(ws, err):
        print(f"[WS error] {err}")

    def on_close(ws, code, msg):
        global _openai_ws
        print(f"[WS closed] {code}")
        _openai_ws = None

    ws = websocket.WebSocketApp(
        f"wss://api.openai.com/v1/realtime?model={REALTIME_MODEL}",
        header={"Authorization": f"Bearer {api_key}"},
        on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close,
    )
    _openai_ws = ws
    ws.run_forever()


def close_ws():
    global _openai_ws
    if _openai_ws:
        try:
            _openai_ws.close()
        except Exception:
            pass
        _openai_ws = None


# ── Socket.IO events ───────────────────────────────────────────────────────────
@socketio.on("connect")
def on_connect():
    print(f"[SIO] connected: {request.sid}")


@socketio.on("disconnect")
def on_disconnect():
    global _current_sid
    print(f"[SIO] disconnected: {request.sid}")
    close_ws()
    _cancel_auto_advance()
    _current_sid = None


@socketio.on("start_story_1")
def on_start_story_1(data):
    global _study_phase, _current_sid, _study_output
    _current_sid = request.sid
    _study_phase = 1
    _study_output = {
        "study_condition": STUDY_CONDITION,
        "study_date": datetime.now().isoformat(),
    }
    _story_save_paths.clear()
    close_ws()
    reset_story(STORY_1_KEY, phase=1)
    threading.Thread(target=run_openai_ws, daemon=True).start()
    print(f"[Study] Story 1 started | condition: {STUDY_CONDITION}")


@socketio.on("start_story_2")
def on_start_story_2(_data):
    global _study_phase, _current_sid
    _current_sid = request.sid
    _study_phase = 2
    close_ws()
    reset_story(STORY_2_KEY, phase=2, time_limit=STORY_2_TIME_LIMIT)
    threading.Thread(target=run_openai_ws, daemon=True).start()
    print(f"[Study] Story 2 started | condition: {STUDY_CONDITION}")


@socketio.on("finish_story")
def on_finish_story(data):
    global _study_phase
    phase = data.get("phase", _study_phase)
    close_ws()
    _cancel_auto_advance()

    with _lock:
        snap = dict(_state)
    transcript_copy = list(_transcript)
    elapsed = 0
    if _monitor:
        try:
            elapsed = _monitor.elapsed_seconds()
        except Exception:
            pass

    story_data = {
        "scenario": snap.get("scenario_name", ""),
        "story_topic": snap.get("story_topic", ""),
        "study_condition": STUDY_CONDITION,
        "director_type": "standard" if phase == 1 else (
            "time_constrained" if STUDY_CONDITION == "A" else "standard_cutoff"
        ),
        "beats_completed": snap["beat_index"],
        "completed_beats": snap["completed_beats"],
        "elapsed_seconds": round(elapsed, 2),
        "turns": transcript_copy,
    }
    if phase == 2:
        story_data["time_limit_minutes"] = STORY_2_TIME_LIMIT

    key = f"story_{phase}"
    _study_output[key] = story_data

    # Immediately write story transcript to its own subfolder
    try:
        subfolder = os.path.join(STUDY_DIR, "outputs", f"story_{phase}")
        os.makedirs(subfolder, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        cond = STUDY_CONDITION.lower()
        path = os.path.join(subfolder, f"story{phase}_{ts}_cond{cond}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(story_data, f, indent=2, ensure_ascii=False)
        _story_save_paths[phase] = path
        print(f"[Study] Story {phase} saved → {path}")
    except Exception as e:
        print(f"[Story {phase} save error] {e}")

    emit("story_finished", {"phase": phase, "turns": len(transcript_copy)})


@socketio.on("cancel_study")
def on_cancel_study(_data):
    global _openai_ws, _study_phase, _current_sid
    print("[cancel_study] participant restarted study")
    ws = _openai_ws
    _openai_ws = None
    _cancel_auto_advance()

    # Save whatever has been collected so far before resetting
    if _study_output:
        try:
            with _lock:
                snap = dict(_state)
            transcript_copy = list(_transcript)
            # Capture the active story transcript if a story was in progress
            if _study_phase in (1, 2) and transcript_copy:
                elapsed = 0
                if _monitor:
                    try:
                        elapsed = _monitor.elapsed_seconds()
                    except Exception:
                        pass
                story_data = {
                    "scenario": snap.get("scenario_name", ""),
                    "story_topic": snap.get("story_topic", ""),
                    "study_condition": STUDY_CONDITION,
                    "director_type": "standard" if _study_phase == 1 else (
                        "time_constrained" if STUDY_CONDITION == "A" else "standard_cutoff"
                    ),
                    "beats_completed": snap["beat_index"],
                    "completed_beats": snap["completed_beats"],
                    "elapsed_seconds": round(elapsed, 2),
                    "turns": transcript_copy,
                    "abandoned_mid_story": True,
                }
                if _study_phase == 2:
                    story_data["time_limit_minutes"] = STORY_2_TIME_LIMIT
                # Only write if not already saved (finish_story already stored it)
                key = f"story_{_study_phase}"
                if key not in _study_output:
                    _study_output[key] = story_data

            subfolder = os.path.join(STUDY_DIR, "outputs", f"story_{_study_phase if _study_phase else 1}")
            os.makedirs(subfolder, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            cond = STUDY_CONDITION.lower()
            path = os.path.join(subfolder, f"story{_study_phase if _study_phase else 1}_{ts}_cond{cond}_abandoned.json")
            save_data = dict(_study_output)
            save_data["abandoned_at"] = datetime.now().isoformat()
            save_data["abandoned_phase"] = _study_phase
            with open(path, "w", encoding="utf-8") as f:
                json.dump(save_data, f, indent=2, ensure_ascii=False)
            print(f"[Study] Abandoned save → {path}")
        except Exception as e:
            print(f"[cancel_study save error] {e}")

    _study_phase = 0
    _current_sid = None
    if ws:
        try:
            ws.close()
        except Exception:
            pass
    if _cond_b_timer:
        try:
            _cond_b_timer.cancel()
        except Exception:
            pass


@socketio.on("text_input")
def on_text_input(data):
    global _last_user_input
    text = data.get("text", "").strip()
    if not text or not _openai_ws:
        return
    _cancel_auto_advance()
    _last_user_input = text
    with _lock:
        _state["story_so_far"] += f"\nUser: {text}"
    _schedule_auto_advance()  # 30s from this input; reset on each new message
    try:
        _openai_ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": text}]},
        }))
        _openai_ws.send(json.dumps({"type": "response.create"}))
    except Exception as e:
        print(f"[text_input error] {e}")


# ── HTTP routes ────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("public", "index.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory("public", path)


@app.route("/time_status")
def time_status():
    if _study_phase != 2:
        return jsonify({"active": False})
    with _lock:
        bi = _state["beat_index"]
        beats = _state["beats"]
        tl = _state.get("time_limit", STORY_2_TIME_LIMIT)

    # Condition A: use TemporalMonitor for elapsed time
    if STUDY_CONDITION == "A" and _monitor:
        si = min(bi, len(beats) - 1) if beats else 0
        t = _monitor.state(si, beats) if beats else {}
        return jsonify({
            "active": True,
            "elapsed_seconds": t.get("elapsed_seconds", 0),
            "remaining_seconds": t.get("remaining_seconds", 0),
            "pacing_mode": t.get("pacing_mode", "normal"),
            "beat_index": bi,
            "total_beats": len(beats),
            "time_limit_minutes": tl,
        })

    # Condition B: no TemporalMonitor; client just shows the wall clock
    return jsonify({
        "active": True,
        "elapsed_seconds": 0,
        "remaining_seconds": tl * 60,
        "pacing_mode": "normal",
        "beat_index": bi,
        "total_beats": len(beats),
        "time_limit_minutes": tl,
    })


@app.route("/state")
def get_state():
    return jsonify(get_snap())


@app.route("/study_info")
def study_info():
    return jsonify({"condition": STUDY_CONDITION, "story_2_time_limit": STORY_2_TIME_LIMIT})


@app.route("/save_questionnaire", methods=["POST"])
def save_questionnaire():
    try:
        data = request.get_json()
        phase = data.get("phase", 1)
        responses = data.get("responses", {})
        _study_output[f"questionnaire_{phase}"] = responses

        # Update the transcript file written at story-end — add questionnaire in place
        path = _story_save_paths.get(phase)
        if not path:
            # Fallback: story file wasn't written yet (edge case), create it now
            subfolder = os.path.join(STUDY_DIR, "outputs", f"story_{phase}")
            os.makedirs(subfolder, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            cond = STUDY_CONDITION.lower()
            path = os.path.join(subfolder, f"story{phase}_{ts}_cond{cond}.json")

        # Load existing file if it exists, otherwise start from _study_output
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                save_data = json.load(f)
        else:
            save_data = dict(_study_output.get(f"story_{phase}", {}))

        save_data["questionnaire"] = responses
        save_data["questionnaire_saved_at"] = datetime.now().isoformat()

        with open(path, "w", encoding="utf-8") as f:
            json.dump(save_data, f, indent=2, ensure_ascii=False)
        print(f"[Study] Story {phase} questionnaire added → {path}")

        return jsonify({"saved": True, "path": path})

    except Exception as e:
        print(f"[save_questionnaire error] {e}")
        return jsonify({"saved": False, "error": str(e)})


if __name__ == "__main__":
    print(f"User Study server (condition {STUDY_CONDITION}) → http://localhost:{PORT}")
    print(f"  Story B: {'paced (condition A)' if STUDY_CONDITION == 'A' else 'director-only cut-off (condition B)'}")
    socketio.run(app, host="0.0.0.0", port=PORT, debug=False, allow_unsafe_werkzeug=True)
