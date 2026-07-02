import os, sys, json, threading, random, time
from datetime import datetime
from flask import Flask, send_from_directory, request, jsonify
from flask_socketio import SocketIO, emit
from dotenv import load_dotenv
from openai import OpenAI
import websocket

load_dotenv()

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
from baseline.main import (
    build_prompt as baseline_build_prompt,
    call_llm as baseline_call_llm,
    safe_json_parse as baseline_safe_json_parse,
    validate_animation as baseline_validate_animation,
)

STORY_1_KEY = "olaf_retells_frozen_1_no_derailment"
STORY_2_KEY = "olaf_retells_red_riding_hood_no_derailment"
STORY_1_TIME_LIMIT = 5.0   # minutes — frontend-enforced hard cutoff
STORY_2_TIME_LIMIT = 3.0   # minutes — server-enforced
AUTO_ADVANCE_SECONDS = 60

_SCENARIO_REGISTRY = {sc["scenario_name"]: sc for sc in NO_DERAILMENT_SCENARIOS}

app = Flask(__name__, static_folder="public")
app.config["SECRET_KEY"] = "olaf-study-2026"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

DIRECTOR_MODEL = "gpt-4o-mini"
REALTIME_MODEL = "gpt-realtime"

api_key = os.getenv("OPENAI_API_KEY")
_client = OpenAI(api_key=api_key)

# ── Study-level state ──────────────────────────────────────────────────────────
# Phases: 0=idle  1=story1_r1  2=story1_r2  3=story2_r1  4=story2_r2
_story1_order: list = []   # ["baseline","director"] or ["director","baseline"]
_story2_order: list = []   # ["director","time_constrained"] or ["time_constrained","director"]
_study_phase: int = 0
_study_output: dict = {}
_session_file_path: str | None = None

# ── Per-round runtime state ────────────────────────────────────────────────────
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
_last_user_activity_ts = 0.0
_time_up_injected = False
_auto_advance_timer: threading.Timer | None = None
_wall_timer: threading.Timer | None = None


# ── Phase helpers ──────────────────────────────────────────────────────────────
def _condition(phase: int) -> str:
    if phase == 1: return _story1_order[0] if _story1_order else "baseline"
    if phase == 2: return _story1_order[1] if _story1_order else "director"
    if phase == 3: return _story2_order[0] if _story2_order else "director"
    if phase == 4: return _story2_order[1] if _story2_order else "time_constrained"
    return "director"

def _story_num(phase: int) -> int:
    return 1 if phase <= 2 else 2

def _round_num(phase: int) -> int:
    return 1 if phase in (1, 3) else 2

def _scenario_key(phase: int) -> str:
    return STORY_1_KEY if phase <= 2 else STORY_2_KEY

def _time_limit(phase: int) -> float:
    return STORY_1_TIME_LIMIT if phase <= 2 else STORY_2_TIME_LIMIT

def get_snap():
    with _lock:
        return dict(_state)


# ── Prompts ────────────────────────────────────────────────────────────────────
def build_prompt(state: dict) -> str:
    cond = _condition(_study_phase)
    if cond == "baseline":
        return _baseline_prompt(state)
    return _director_prompt(state, timed=(cond == "time_constrained"))


def _baseline_prompt(state: dict) -> str:
    """Prompt used by the Realtime API session (system instructions only, no user_input)."""
    beats = state["beats"]
    idx = state["beat_index"]
    si = min(idx, len(beats) - 1)
    cb = beats[si]
    tail = state["story_so_far"][-600:] if state["story_so_far"] else "(story just started)"
    return f"""You are Olaf the snowman, telling an interactive story. Speak AS Olaf — stay fully in character.

{OLAF_CHARACTER["character_prompt"]}

## Story Topic
{state["story_topic"]}

## Rules
- Keep responses short: 2–4 sentences, natural when read.
- Engage warmly with whatever the user says, then gently guide the story forward.
- Do NOT mention any system or director. Just be Olaf.
- Vary tone: excited, curious, gentle.
- Do not start most turns with "Oh". Do not repeat the same phrases.

## Current beat
Beat {idx + 1} of {len(beats)}: {cb["name"]} — {cb["goal"]}

Story so far:
{tail}""".strip()


def _handle_baseline_input(text: str):
    """Call baseline/main.py directly — no director, just Olaf."""
    with _lock:
        snap = dict(_state)
        _state["story_so_far"] += f"\nUser: {text}"

    beats = snap["beats"]
    story_state = {
        "beat_index": snap["beat_index"],
        "completed_beats": snap["completed_beats"],
        # Same tail-only window as _director_prompt, so neither condition
        # gets an unfair amount of story history in its prompt.
        "story_so_far": snap["story_so_far"][-600:],
    }
    current_beat_name = beats[min(snap["beat_index"], len(beats) - 1)]["name"]

    prompt = baseline_build_prompt(text, story_state, OLAF_CHARACTER, snap["story_topic"], beats)

    try:
        raw = baseline_call_llm(prompt)
    except Exception as e:
        print(f"[baseline LLM error] {e}")
        raw = json.dumps({
            "character_response": "Hmm, something melted in my head. Let me try again!",
            "story_event": "A brief pause.",
            "animation": OLAF_CHARACTER["available_animations"][0],
            "beat_completed": False,
            "reason": "API error.",
        })

    output = baseline_safe_json_parse(raw, OLAF_CHARACTER["available_animations"][0])
    output["animation"] = baseline_validate_animation(output.get("animation", ""), OLAF_CHARACTER)
    olaf_text = output.get("character_response", "").strip()
    beat_completed = output.get("beat_completed", False)

    with _lock:
        _state["story_so_far"] += f"\nOlaf: {olaf_text}\n"
        _state["turns_in_current_beat"] = snap.get("turns_in_current_beat", 0) + 1
        if beat_completed and snap["beat_index"] < len(beats):
            _state["completed_beats"].append(beats[snap["beat_index"]]["name"])
            _state["beat_index"] += 1
            _state["turns_in_current_beat"] = 0
            print(f"[Baseline beat → {_state['beat_index']} (model)]")

    _transcript.append({
        "turn": len(_transcript) + 1,
        "beat": current_beat_name,
        "user_input": text,
        "character_response": olaf_text,
        "model_output": output,
        "condition": "baseline",
    })

    if _current_sid:
        socketio.emit("transcript_assistant", {"delta": olaf_text}, room=_current_sid)
        socketio.emit("response_done", {}, room=_current_sid)

    _schedule_auto_advance()


def _director_prompt(state: dict, timed: bool) -> str:
    beats = state["beats"]
    idx = state["beat_index"]
    si = min(idx, len(beats) - 1)
    cb = beats[si]
    nb = beats[si + 1]["name"] if si < len(beats) - 1 else "None"
    tail = state["story_so_far"][-600:] if state["story_so_far"] else "(story just started)"
    tl = state.get("time_limit", 3.0)

    time_line = f"\nThe story has a target duration of {tl} minutes.\n" if timed else ""
    pacing = """
## Pacing Rules (from pacing_mode in tool result)
- too_fast: ahead of schedule — expand beat. Use expansion_hint if present.
- normal: continue naturally.
- hurry: progress faster, avoid lingering.
- critical: compress, move toward ending quickly.
- final: time is up — close all remaining beats now in one response.
""" if timed else ""

    return f"""You are an interactive storytelling engine voicing Olaf the snowman.
You speak AS Olaf. Stay fully in character at all times.{time_line}
CRITICAL: Before EVERY response you MUST call the get_director_decision tool.
Do not speak until you have the director's instruction.

{OLAF_CHARACTER["character_prompt"]}

## Story Topic
{state["story_topic"]}

## Actor Rules
- Speak only as Olaf. Never mention the Director or the tool.
- Keep responses short: 2–4 sentences, natural when read.
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


# ── Auto-advance ───────────────────────────────────────────────────────────────
def _cancel_auto_advance():
    global _auto_advance_timer
    if _auto_advance_timer:
        _auto_advance_timer.cancel()
        _auto_advance_timer = None


def _schedule_auto_advance():
    _cancel_auto_advance()
    global _auto_advance_timer

    def _fire():
        if not _current_sid:
            return
        # threading.Timer.cancel() cannot stop a timer whose callback has
        # already started running — if the user's real input lands in that
        # narrow window, _cancel_auto_advance() (called from on_text_input)
        # is a no-op and this still fires. Re-validate idle time here so a
        # stale fire backs off instead of racing a real user turn: sending
        # two concurrent response.create calls on the same Realtime session
        # gets the second one rejected, silently dropping that turn (no
        # director_decision, no character response, no transcript entry).
        idle_for = time.time() - _last_user_activity_ts
        if idle_for < AUTO_ADVANCE_SECONDS - 1:
            _schedule_auto_advance()
            return
        cond = _condition(_study_phase)
        if cond == "baseline":
            threading.Thread(
                target=_handle_baseline_input,
                args=("[The user is listening — continue the story naturally]",),
                daemon=True,
            ).start()
            return
        if not _openai_ws:
            return
        with _lock:
            _state["story_so_far"] += "\nUser: (no response)"
        try:
            _openai_ws.send(json.dumps({
                "type": "conversation.item.create",
                "item": {"type": "message", "role": "user",
                         "content": [{"type": "input_text",
                                      "text": "[The user is listening — continue the story naturally]"}]},
            }))
            _openai_ws.send(json.dumps({"type": "response.create", "response": {"tool_choice": "required"}}))
        except Exception as e:
            print(f"[auto-advance error] {e}")
            return
        _schedule_auto_advance()

    _auto_advance_timer = threading.Timer(AUTO_ADVANCE_SECONDS, _fire)
    _auto_advance_timer.daemon = True
    _auto_advance_timer.start()


# ── Wall-clock timer (director mode in story 2) ───────────────────────────────
def _start_wall_timer(time_limit_minutes: float):
    global _wall_timer
    _cancel_wall_timer()

    def _fire():
        global _time_up_injected
        if not _time_up_injected:
            _time_up_injected = True
            if _current_sid:
                socketio.emit("time_up", {}, room=_current_sid)
        threading.Thread(target=_auto_finish_active_phase, daemon=True).start()

    _wall_timer = threading.Timer(time_limit_minutes * 60, _fire)
    _wall_timer.daemon = True
    _wall_timer.start()


def _cancel_wall_timer():
    global _wall_timer
    if _wall_timer:
        try:
            _wall_timer.cancel()
        except Exception:
            pass
        _wall_timer = None


# ── Reset per-round state ──────────────────────────────────────────────────────
def reset_story(phase: int):
    global _transcript, _monitor, _last_user_input, _last_user_activity_ts, _time_up_injected
    cond = _condition(phase)
    sc = _SCENARIO_REGISTRY[_scenario_key(phase)]
    tl = _time_limit(phase)

    with _lock:
        _state.update({
            "beats": sc["beats"], "story_topic": sc["story_topic"],
            "scenario_name": _scenario_key(phase), "beat_index": 0,
            "completed_beats": [], "story_so_far": "",
            "turns_in_current_beat": 0, "expansion_index": 0,
            "time_limit": tl,
        })
    _transcript = []
    _last_user_input = ""
    _last_user_activity_ts = time.time()
    _time_up_injected = False
    _cancel_auto_advance()
    _cancel_wall_timer()
    _monitor = None

    if phase in (3, 4):
        if cond == "time_constrained":
            _monitor = TemporalMonitor(
                time_limit_minutes=tl,
                total_beats=len(sc["beats"]),
                final_buffer_seconds=30.0,
            )
        else:
            _start_wall_timer(tl)


# ── Director tool handler ──────────────────────────────────────────────────────
def handle_director_tool(ws, event: dict):
    global _last_user_input, _time_up_injected

    cond = _condition(_study_phase)
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

    if cond == "director":
        try:
            decision = get_director_decision(
                client=_client, model=DIRECTOR_MODEL,
                user_input=user_input, story_state=snap,
                character=OLAF_CHARACTER, story_topic=snap["story_topic"],
                beats=beats,
            )
        except Exception as e:
            print(f"[director error] {e}")
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

    elif cond == "time_constrained":
        temporal = _monitor.state(si, beats) if _monitor else {
            "elapsed_seconds": 0, "remaining_seconds": snap["time_limit"] * 60, "pacing_mode": "normal",
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
            print(f"[tc-director error] {e}")
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
        print(f"[TC | {pacing_mode} | {temporal.get('remaining_seconds', 0):.0f}s left]")
    else:
        return

    # Refresh the system prompt with the latest beat/story state — same
    # pattern as Real-Time-API-Demo's build_system_prompt(state_now). The
    # director_instruction itself travels natively via the tool's
    # function_call_output below, not baked into these instructions.
    snap_now = get_snap()
    instructions = _director_prompt(snap_now, timed=(cond == "time_constrained"))
    ws.send(json.dumps({
        "type": "session.update",
        "session": {"type": "realtime", "instructions": instructions},
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
    if temporal:
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

    if (cond == "time_constrained" and _monitor
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


# ── Save helpers ───────────────────────────────────────────────────────────────
def _write_session_file():
    if not _session_file_path:
        return
    try:
        with open(_session_file_path, "w", encoding="utf-8") as f:
            json.dump(_study_output, f, indent=2, ensure_ascii=False)
        print(f"[Study] Session file updated → {_session_file_path}")
    except Exception as e:
        print(f"[write_session_file error] {e}")


def _save_phase_data(phase: int, transcript_copy: list, snap: dict,
                     elapsed: float = 0, abandoned: bool = False) -> None:
    cond = _condition(phase)
    phase_data = {
        "condition": cond,
        "story": _story_num(phase),
        "round": _round_num(phase),
        "scenario": snap.get("scenario_name", ""),
        "story_topic": snap.get("story_topic", ""),
        "beats_completed": snap["beat_index"],
        "completed_beats": snap["completed_beats"],
        "elapsed_seconds": round(elapsed, 2),
        "time_limit_minutes": _time_limit(phase),
        "story_so_far": snap.get("story_so_far", ""),
        "turns": transcript_copy,
    }
    if abandoned:
        phase_data["abandoned"] = True

    _study_output.setdefault("phases", {})[str(phase)] = phase_data
    _write_session_file()
    print(f"[Study] Phase {phase} ({cond}) saved to session file")


def _auto_finish_active_phase():
    import time as _time
    _time.sleep(1.0)
    phase = _study_phase
    with _lock:
        snap = dict(_state)
    transcript_copy = list(_transcript)
    elapsed = 0
    if _monitor:
        try:
            elapsed = _monitor.elapsed_seconds()
        except Exception:
            pass
    _save_phase_data(phase, transcript_copy, snap, elapsed)
    print(f"[Study] Phase {phase} auto-finished ({len(transcript_copy)} turns)")
    if _current_sid:
        socketio.emit("story_finished", {"phase": phase, "turns": len(transcript_copy)}, room=_current_sid)
    close_ws()


# ── OpenAI Realtime WebSocket ──────────────────────────────────────────────────
def run_openai_ws():
    global _openai_ws

    def on_open(ws):
        cond = _condition(_study_phase)
        state = get_snap()
        session_cfg = {
            "type": "realtime",
            "output_modalities": ["text"],
            "instructions": build_prompt(state),
            "tool_choice": "auto",
        }
        if cond != "baseline":
            session_cfg["tools"] = [DIRECTOR_TOOL]
        ws.send(json.dumps({"type": "session.update", "session": session_cfg}))
        print(f"[WS] connected (phase {_study_phase}, condition {cond})")

    def on_message(ws, message):
        global _last_user_input
        try:
            data = json.loads(message)
        except Exception:
            return
        etype = data.get("type", "")

        if etype == "session.created":
            if _current_sid:
                socketio.emit("session_started", {"phase": _study_phase}, room=_current_sid)

        elif etype in ("response.text.delta", "response.audio_transcript.delta",
                       "response.output_audio_transcript.delta"):
            delta = data.get("delta", "")
            if delta and _current_sid:
                socketio.emit("transcript_assistant", {"delta": delta}, room=_current_sid)

        elif etype == "response.function_call_arguments.done":
            if data.get("name") == "get_director_decision":
                threading.Thread(target=handle_director_tool, args=(ws, data), daemon=True).start()

        elif etype == "response.done":
            cond = _condition(_study_phase)
            olaf_text = ""
            try:
                for item in data.get("response", {}).get("output", []):
                    for part in item.get("content", []):
                        olaf_text += part.get("transcript") or part.get("text") or ""
            except Exception:
                pass

            if olaf_text:
                with _lock:
                    _state["story_so_far"] += f"\nOlaf: {olaf_text}\n"
                if cond == "baseline":
                    # Baseline uses WebSocket fallback path (shouldn't reach here normally)
                    _transcript.append({
                        "turn": len(_transcript) + 1,
                        "user_input": _last_user_input or "(auto-advance)",
                        "character_response": olaf_text,
                        "condition": "baseline",
                    })
                elif _transcript:
                    _transcript[-1]["character_response"] = olaf_text
                # gpt-realtime sends full text in response.done, not via text.delta events
                if _current_sid:
                    socketio.emit("transcript_assistant", {"delta": olaf_text}, room=_current_sid)

            if _current_sid:
                socketio.emit("response_done", {}, room=_current_sid)
            _schedule_auto_advance()

            # One "final" turn produces two response.done events: the tool
            # call itself (no text) fires first, then the actual closing
            # narration (real text) fires later once handle_director_tool's
            # own response.create resolves. Only auto-finish on the one that
            # actually delivered text — otherwise this can race and tear
            # down the connection (close_ws) before the wrap-up ever streams
            # back, since _time_up_injected is set synchronously as soon as
            # pacing_mode hits "final", before either response.done arrives.
            if _study_phase in (3, 4) and _time_up_injected and olaf_text:
                threading.Thread(target=_auto_finish_active_phase, daemon=True).start()

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
    _cancel_wall_timer()
    _current_sid = None


@socketio.on("begin_study")
def on_begin_study(_data):
    global _story1_order, _story2_order, _current_sid, _study_output, _study_phase, _session_file_path
    _current_sid = request.sid
    _study_phase = 0
    _story1_order = random.sample(["baseline", "director"], 2)
    _story2_order = random.sample(["director", "time_constrained"], 2)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    subfolder = os.path.join(STUDY_DIR, "outputs")
    os.makedirs(subfolder, exist_ok=True)
    _session_file_path = os.path.join(subfolder, f"session_{ts}.json")

    _study_output = {
        "study_date": datetime.now().isoformat(),
        "story1_order": _story1_order,
        "story2_order": _story2_order,
        "phases": {},
    }
    _write_session_file()
    emit("study_ready", {
        "story1_order": _story1_order,
        "story2_order": _story2_order,
    })
    print(f"[Study] Randomized — S1: {_story1_order}  S2: {_story2_order}  file: {_session_file_path}")


@socketio.on("start_phase")
def on_start_phase(data):
    global _study_phase, _current_sid
    phase = data.get("phase")
    if phase not in (1, 2, 3, 4):
        return
    _current_sid = request.sid
    _study_phase = phase
    close_ws()
    reset_story(phase)
    cond = _condition(phase)
    if cond == "baseline":
        # Baseline uses regular chat API — no Realtime WebSocket needed.
        emit("session_started", {"phase": phase})
        _schedule_auto_advance()
    else:
        threading.Thread(target=run_openai_ws, daemon=True).start()
    print(f"[Study] Phase {phase} started (condition: {cond})")


@socketio.on("finish_story")
def on_finish_story(data):
    phase = data.get("phase", _study_phase)
    close_ws()
    _cancel_auto_advance()
    _cancel_wall_timer()

    with _lock:
        snap = dict(_state)
    transcript_copy = list(_transcript)
    elapsed = 0
    if _monitor:
        try:
            elapsed = _monitor.elapsed_seconds()
        except Exception:
            pass

    _save_phase_data(phase, transcript_copy, snap, elapsed)
    emit("story_finished", {"phase": phase, "turns": len(transcript_copy)})


@socketio.on("cancel_study")
def on_cancel_study(_data):
    global _study_phase, _current_sid
    print("[cancel_study] participant restarted")
    close_ws()
    _cancel_auto_advance()
    _cancel_wall_timer()

    if _study_output and _study_phase > 0:
        try:
            with _lock:
                snap = dict(_state)
            transcript_copy = list(_transcript)
            elapsed = 0
            if _monitor:
                try:
                    elapsed = _monitor.elapsed_seconds()
                except Exception:
                    pass
            _study_output["abandoned_at_phase"] = _study_phase
            if transcript_copy or snap.get("story_so_far"):
                _save_phase_data(_study_phase, transcript_copy, snap, elapsed, abandoned=True)
            else:
                _write_session_file()
        except Exception as e:
            print(f"[cancel_study save error] {e}")

    _study_phase = 0
    _current_sid = None


@socketio.on("text_input")
def on_text_input(data):
    global _last_user_input, _last_user_activity_ts
    text = data.get("text", "").strip()
    if not text:
        return
    _last_user_activity_ts = time.time()
    _cancel_auto_advance()
    _last_user_input = text
    cond = _condition(_study_phase)
    if cond == "baseline":
        threading.Thread(target=_handle_baseline_input, args=(text,), daemon=True).start()
        return
    if not _openai_ws:
        return
    with _lock:
        _state["story_so_far"] += f"\nUser: {text}"
    try:
        _openai_ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": text}]},
        }))
        _openai_ws.send(json.dumps({"type": "response.create", "response": {"tool_choice": "required"}}))
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
    if _study_phase not in (3, 4):
        return jsonify({"active": False})
    cond = _condition(_study_phase)
    with _lock:
        bi = _state["beat_index"]
        beats = _state["beats"]
        tl = _state.get("time_limit", STORY_2_TIME_LIMIT)

    if cond == "time_constrained" and _monitor:
        si = min(bi, len(beats) - 1) if beats else 0
        t = _monitor.state(si, beats) if beats else {}
        return jsonify({
            "active": True,
            "elapsed_seconds": t.get("elapsed_seconds", 0),
            "remaining_seconds": t.get("remaining_seconds", 0),
            "pacing_mode": t.get("pacing_mode", "normal"),
            "beat_index": bi, "total_beats": len(beats),
            "time_limit_minutes": tl,
        })

    return jsonify({
        "active": True,
        "elapsed_seconds": 0,
        "remaining_seconds": tl * 60,
        "pacing_mode": "normal",
        "beat_index": bi, "total_beats": len(beats),
        "time_limit_minutes": tl,
    })


@app.route("/state")
def get_state():
    return jsonify(get_snap())


@app.route("/study_setup")
def study_setup():
    return jsonify({"story1_order": _story1_order, "story2_order": _story2_order})


@app.route("/study_info")
def study_info():
    return jsonify({
        "story_1_time_limit": STORY_1_TIME_LIMIT,
        "story_2_time_limit": STORY_2_TIME_LIMIT,
        "story1_order": _story1_order,
        "story2_order": _story2_order,
    })


@app.route("/save_questionnaire", methods=["POST"])
def save_questionnaire():
    try:
        data = request.get_json()
        phase = data.get("phase")
        responses = data.get("responses", {})

        phase_entry = _study_output.setdefault("phases", {}).setdefault(str(phase), {})
        phase_entry["questionnaire"] = responses
        phase_entry["questionnaire_saved_at"] = datetime.now().isoformat()
        _write_session_file()

        print(f"[Study] Phase {phase} questionnaire saved → {_session_file_path}")
        return jsonify({"saved": True, "path": _session_file_path})
    except Exception as e:
        print(f"[save_questionnaire error] {e}")
        return jsonify({"saved": False, "error": str(e)})


if __name__ == "__main__":
    PORT = int(os.getenv("PORT", 3003))
    print(f"User Study server → http://localhost:{PORT}")
    socketio.run(app, host="0.0.0.0", port=PORT, debug=False, allow_unsafe_werkzeug=True)
