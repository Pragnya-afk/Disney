import os
import sys
import json
import base64
import threading
import glob
import importlib
from datetime import datetime
import numpy as np
from flask import Flask, send_from_directory, request, jsonify
from flask_socketio import SocketIO, emit
from dotenv import load_dotenv
from openai import OpenAI
import websocket

load_dotenv()

# ── Path setup ─────────────────────────────────────────────────────────────────
REAL_TIME_DIR = os.path.dirname(os.path.abspath(__file__))
IMPLEMENTATION_DIR = os.path.join(os.path.dirname(REAL_TIME_DIR), "Disney", "Implementation")
if not os.path.isdir(IMPLEMENTATION_DIR):
    IMPLEMENTATION_DIR = os.path.join(os.path.dirname(REAL_TIME_DIR), "Implementation")
sys.path.insert(0, IMPLEMENTATION_DIR)
sys.path.insert(0, os.path.join(IMPLEMENTATION_DIR, "director_agent"))
sys.path.insert(0, os.path.join(IMPLEMENTATION_DIR, "director_agent", "time_constrained"))

load_dotenv(os.path.join(IMPLEMENTATION_DIR, ".env"))

from time_director_core import get_time_director_decision
from time_control import TemporalMonitor
from character_prompts.olaf import CHARACTER as OLAF_CHARACTER
from scenarios.olaf_derailment_scenario_suite import NO_DERAILMENT_SCENARIOS
from audio_fx import get_fx_chain

OLAF_AUDIOFX_CONFIG = {
    "pitch_shift": {"semitones": 2},
    "reverb": {"room_size": 0.25, "dry_level": 0.85, "wet_level": 0.15},
}


def apply_fx(pcm: bytes, fx_chain, sample_rate: int = 24_000) -> bytes:
    if fx_chain is None or len(pcm) == 0:
        return pcm
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    processed = fx_chain(audio, sample_rate)
    clipped = np.clip(processed, -1.0, 1.0)
    return (clipped * 32767).astype(np.int16).tobytes()

# ── Config ─────────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder="public")
app.config["SECRET_KEY"] = "olaf-tc-demo-secret"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
PORT = int(os.getenv("PORT", 3002))

DIRECTOR_MODEL = "gpt-4o-mini"
REALTIME_MODEL = "gpt-realtime"
AUDIO_SAMPLE_RATE = 24_000

api_key = os.getenv("OPENAI_API_KEY")
_openai_client = OpenAI(api_key=api_key)
olaf_fx = get_fx_chain(OLAF_AUDIOFX_CONFIG)

# ── Scenario registry ──────────────────────────────────────────────────────────
_SUITE_FILE = "olaf_derailment_scenario_suite"
_SKIP_FILES = {_SUITE_FILE, "__init__"}
_SKIP_PATTERNS = ("medium_derail", "complete_derail")



def _make_label(key: str) -> str:
    label = key.replace("_no_derailment", "").replace("_", " ")
    return " ".join(w.capitalize() for w in label.split())


def _build_registry() -> dict:
    registry = {}
    pattern = os.path.join(IMPLEMENTATION_DIR, "scenarios", "*.py")
    for path in sorted(glob.glob(pattern)):
        module_name = os.path.splitext(os.path.basename(path))[0]
        if module_name in _SKIP_FILES or module_name.startswith("_") or any(p in module_name for p in _SKIP_PATTERNS):
            continue
        try:
            mod = importlib.import_module(f"scenarios.{module_name}")
            sc = getattr(mod, "SCENARIO", None)
            if sc and "beats" in sc and "story_topic" in sc:
                key = sc.get("scenario_name", module_name)
                registry[key] = sc
        except Exception as e:
            print(f"[scenario loader] skipping {module_name}: {e}")
    for sc in NO_DERAILMENT_SCENARIOS:
        registry[sc["scenario_name"]] = sc
    return registry


_SCENARIO_REGISTRY = _build_registry()

AVAILABLE_SCENARIOS = {
    k: _make_label(k)
    for k in _SCENARIO_REGISTRY
    if k.endswith("_no_derailment")
}

# ── Session state ──────────────────────────────────────────────────────────────
_state: dict = {
    "beat_index": 0,
    "completed_beats": [],
    "story_so_far": "",
    "turns_in_current_beat": 0,
    "beats": [],
    "story_topic": "",
    "scenario_name": "",
    "time_limit": 5.0,
}
_lock = threading.Lock()
_character = OLAF_CHARACTER
_monitor: TemporalMonitor | None = None
_transcript: list = []
_openai_ws = None
_current_sid = None
_last_user_input = ""
_time_up_injected = False


def reset_state(scenario_key: str, time_limit: float = 5.0):
    global _character, _transcript, _monitor, _last_user_input, _time_up_injected
    scenario = _SCENARIO_REGISTRY[scenario_key]
    with _lock:
        _state["beats"] = scenario["beats"]
        _state["story_topic"] = scenario["story_topic"]
        _state["scenario_name"] = scenario_key
        _state["beat_index"] = 0
        _state["completed_beats"] = []
        _state["story_so_far"] = ""
        _state["turns_in_current_beat"] = 0
        _state["time_limit"] = time_limit
        _state["expansion_index"] = 0
    _character = OLAF_CHARACTER
    _transcript = []
    _last_user_input = ""
    _time_up_injected = False
    time_limit_seconds = time_limit * 60
    final_buffer = max(30.0, min(60.0, time_limit_seconds * 0.30))
    _monitor = TemporalMonitor(
        time_limit_minutes=time_limit,
        total_beats=len(_state["beats"]),
        final_buffer_seconds=final_buffer,
    )


def get_state_snapshot():
    with _lock:
        return dict(_state)


# ── System prompt ──────────────────────────────────────────────────────────────
def build_system_prompt(state: dict) -> str:
    beats = state["beats"]
    idx = state["beat_index"]
    safe_idx = min(idx, len(beats) - 1)
    current_beat = beats[safe_idx]
    next_beat = beats[safe_idx + 1]["name"] if safe_idx < len(beats) - 1 else "None"
    story_tail = state["story_so_far"][-600:] if state["story_so_far"] else "(story just started)"
    time_limit = state.get("time_limit", 5.0)

    return f"""
You are an interactive storytelling engine voicing {_character['name']}.
You speak AS {_character['name']}. Stay fully in character at all times.
The story has a target duration of {time_limit} minutes.

CRITICAL: Before EVERY response you MUST call the get_director_decision tool.
Do not speak until you have received the director's instruction.
Use the returned director_instruction AND pacing_mode to guide exactly what you say.

{_character["character_prompt"]}

## Story Topic
{state["story_topic"]}

## Actor Rules
- Speak only as {_character['name']}. Never mention the Director or the tool.
- Keep responses short: 2–4 sentences, natural spoken aloud.
- The response must contain a concrete story development.
- The director_instruction in the tool result is mandatory — realize it.
- Vary tone: sometimes excited, sometimes curious, sometimes gentle.
- Do not start most turns with "Oh". Do not repeat the same phrases.

## Pacing Rules (from tool result pacing_mode field)
- too_fast: story is ahead of schedule — do NOT finish this beat. If expansion_hint is in the tool result, develop that specific angle fully. Otherwise add emotional depth, sensory detail, or character reaction.
- normal: continue naturally, no rush.
- hurry: make faster progress, avoid lingering.
- critical: compress story events, move toward the ending quickly.
- final: time is up — give a complete, satisfying ending NOW covering all remaining beats.

## Current Story State
Beat {idx + 1} of {len(beats)}: {current_beat["name"]}
Goal: {current_beat["goal"]}
Next beat: {next_beat}
Completed: {json.dumps(state["completed_beats"])}

Story so far:
{story_tail}
""".strip()


DIRECTOR_TOOL = {
    "type": "function",
    "name": "get_director_decision",
    "description": (
        "Get the time-aware director's instruction for this story turn. "
        "Call this BEFORE every response. "
        "Use the returned director_instruction and pacing_mode to guide what the character says."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "user_input": {"type": "string", "description": "What the user just said."}
        },
        "required": ["user_input"],
    },
}

# ── Director tool handler ──────────────────────────────────────────────────────

def handle_director_tool(ws, event: dict):
    global _last_user_input, _time_up_injected
    args = json.loads(event.get("arguments", "{}"))
    user_input = args.get("user_input") or _last_user_input or "(no input)"

    with _lock:
        _state["turns_in_current_beat"] += 1
        state_snapshot = dict(_state)

    beats = state_snapshot["beats"]
    safe_idx = min(state_snapshot["beat_index"], len(beats) - 1)

    if _monitor is not None:
        temporal_state = _monitor.state(safe_idx, beats)
    else:
        temporal_state = {
            "elapsed_seconds": 0,
            "remaining_seconds": state_snapshot.get("time_limit", 5.0) * 60,
            "time_limit_seconds": state_snapshot.get("time_limit", 5.0) * 60,
            "current_beat_index": safe_idx,
            "total_beats": len(beats),
            "completed_beats_count": safe_idx,
            "remaining_beats_count": len(beats) - safe_idx,
            "expected_progress": 0.0,
            "actual_progress": 0.0,
            "pacing_mode": "normal",
            "remaining_beats": beats[safe_idx:],
        }

    try:
        decision = get_time_director_decision(
            client=_openai_client,
            model=DIRECTOR_MODEL,
            user_input=user_input,
            story_state=state_snapshot,
            character=_character,
            story_topic=state_snapshot["story_topic"],
            beats=beats,
            temporal_state=temporal_state,
        )
    except Exception as e:
        print(f"[Director error] {e}")
        decision = {
            "director_instruction": "Continue the story naturally.",
            "decision_type": "progress_story",
        }

    current_beat = beats[safe_idx]
    next_beat = beats[safe_idx + 1]["name"] if safe_idx < len(beats) - 1 else "None"
    pacing_mode = temporal_state.get("pacing_mode", "normal")

    # Build importance-aware coverage instruction before advancing state
    _importance_order = {"high": 0, "medium": 1, "low": 2}

    def _remaining_beat_lines(from_idx):
        remaining = beats[from_idx:]
        sorted_beats = sorted(remaining, key=lambda b: _importance_order.get(b.get("importance", "medium"), 1))
        return [
            f"- {b['name']} [{b.get('importance','medium').upper()}]: {b['goal']}"
            for b in sorted_beats
        ]

    # ── Pacing enforcement ─────────────────────────────────────────────────────
    suggested_expansion = None

    if pacing_mode == "too_fast":
        # Block beat completion and inject the next unused expansion hint
        decision["should_complete_beat"] = False
        expansions = current_beat.get("expansions", [])
        exp_idx = state_snapshot.get("expansion_index", 0)
        if exp_idx < len(expansions):
            suggested_expansion = expansions[exp_idx]
            with _lock:
                _state["expansion_index"] = exp_idx + 1
            decision["director_instruction"] = (
                "The story is ahead of schedule — do NOT complete this beat yet. "
                f"Expand it using this angle: {suggested_expansion}"
            )
        else:
            decision["director_instruction"] = (
                "The story is ahead of schedule — do NOT complete this beat. "
                "Enrich it further with emotional depth, sensory detail, or a warm aside."
            )

    elif pacing_mode == "final":
        decision["should_complete_beat"] = True
        decision["decision_type"] = "close_story"
        lines = _remaining_beat_lines(safe_idx)
        decision["director_instruction"] = (
            "FINAL RESPONSE — close the story now in a single response. "
            "Cover ALL remaining beats below. HIGH-importance beats must be meaningfully narrated. "
            "MEDIUM can be one sentence. LOW can be skipped if needed.\n"
            + "\n".join(lines)
        )

    elif pacing_mode == "hurry":
        turns_in_beat = state_snapshot.get("turns_in_current_beat", 0)
        if turns_in_beat >= 2:
            decision["should_complete_beat"] = True
            decision["director_instruction"] = (
                decision.get("director_instruction", "") +
                " Wrap up this beat now and move on — the story needs to progress."
            )

    elif pacing_mode == "critical":
        decision["should_complete_beat"] = True
        next_high = next(
            (b for b in beats[safe_idx + 1:] if b.get("importance") == "high"), None
        )
        if next_high and "director_instruction" in decision:
            decision["director_instruction"] += (
                f" Then immediately bridge to the next key beat: "
                f"{next_high['name']} — {next_high['goal']}"
            )

    if decision.get("should_complete_beat"):
        with _lock:
            idx = _state["beat_index"]
            if pacing_mode == "final":
                for beat in beats[idx:]:
                    _state["completed_beats"].append(beat["name"])
                _state["beat_index"] = len(beats)
            elif idx < len(beats):
                _state["completed_beats"].append(beats[idx]["name"])
                _state["beat_index"] += 1
            _state["turns_in_current_beat"] = 0
            _state["expansion_index"] = 0
            print(f"[Beat complete → beat {_state['beat_index']} | pacing: {pacing_mode}]")

    state_now = get_state_snapshot()
    ws.send(json.dumps({
        "type": "session.update",
        "session": {"type": "realtime", "instructions": build_system_prompt(state_now)},
    }))

    tool_result = {
        "director_instruction": decision.get("director_instruction", ""),
        "decision_type": decision.get("decision_type", "progress_story"),
        "pacing_mode": pacing_mode,
        "elapsed_seconds": temporal_state.get("elapsed_seconds", 0),
        "remaining_seconds": temporal_state.get("remaining_seconds", 0),
        "current_beat": current_beat["name"],
        "current_beat_goal": current_beat["goal"],
        "next_beat": next_beat,
        "story_so_far_tail": state_snapshot["story_so_far"][-300:],
    }
    if suggested_expansion:
        tool_result["expansion_hint"] = suggested_expansion

    print(
        f"[Director: {decision.get('decision_type')} | Pacing: {pacing_mode} | "
        f"Remaining: {temporal_state.get('remaining_seconds', 0):.0f}s] "
        f"{decision.get('director_instruction', '')[:60]}..."
    )

    if _current_sid:
        socketio.emit("director_decision", {
            "decision_type": decision.get("decision_type"),
            "instruction": decision.get("director_instruction", "")[:80],
            "pacing_mode": pacing_mode,
            "elapsed_seconds": temporal_state.get("elapsed_seconds", 0),
            "remaining_seconds": temporal_state.get("remaining_seconds", 0),
        }, room=_current_sid)

    _transcript.append({
        "turn": len(_transcript) + 1,
        "beat": current_beat["name"],
        "user_input": user_input,
        "director_decision": decision,
        "pacing_mode": pacing_mode,
        "elapsed_seconds": temporal_state.get("elapsed_seconds", 0),
        "remaining_seconds": temporal_state.get("remaining_seconds", 0),
        "character_response": "",
    })

    ws.send(json.dumps({
        "type": "conversation.item.create",
        "item": {
            "type": "function_call_output",
            "call_id": event["call_id"],
            "output": json.dumps(tool_result),
        },
    }))
    ws.send(json.dumps({"type": "response.create"}))

    # Inject story-close message when time's up (once only)
    if _monitor and _monitor.should_stop_for_time() and not _time_up_injected:
        _time_up_injected = True
        if _current_sid:
            socketio.emit("time_up", {}, room=_current_sid)
        ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{
                    "type": "input_text",
                    "text": "[Story time ended — wrap up all remaining story beats immediately with a complete, satisfying ending]",
                }],
            },
        }))
        ws.send(json.dumps({"type": "response.create"}))


# ── OpenAI Realtime WebSocket ──────────────────────────────────────────────────

def run_openai_ws():
    global _openai_ws

    def on_open(ws):
        state = get_state_snapshot()
        ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "type": "realtime",
                "instructions": build_system_prompt(state),
                "audio": {
                    "output": {"voice": "verse"},
                    "input": {
                        "transcription": {"model": "whisper-1"},
                        "turn_detection": {
                            "type": "server_vad",
                            "silence_duration_ms": 700,
                            "threshold": 0.5,
                        },
                    },
                },
                "tools": [DIRECTOR_TOOL],
                "tool_choice": "auto",
            },
        }))
        print("[OpenAI WS] connected, session configured")

    def on_message(ws, message):
        global _last_user_input
        try:
            data = json.loads(message)
        except Exception:
            return

        etype = data.get("type", "")

        if etype == "session.created":
            if _current_sid:
                socketio.emit("session_started", {
                    "scenario": _state.get("scenario_name", ""),
                    "time_limit": _state.get("time_limit", 5.0),
                }, room=_current_sid)

        elif etype == "response.output_audio.delta":
            pcm = base64.b64decode(data["delta"])
            if olaf_fx:
                try:
                    pcm = apply_fx(pcm, olaf_fx, AUDIO_SAMPLE_RATE)
                except Exception as e:
                    print(f"[FX error] {e}")
            if _current_sid:
                socketio.emit("audio_output", {
                    "audio": base64.b64encode(pcm).decode()
                }, room=_current_sid)

        elif etype == "response.output_audio_transcript.delta":
            delta = data.get("delta", "")
            if delta and _current_sid:
                socketio.emit("transcript_assistant", {"delta": delta}, room=_current_sid)

        elif etype == "conversation.item.input_audio_transcription.completed":
            transcript = data.get("transcript", "").strip()
            _last_user_input = transcript
            if transcript and _current_sid:
                socketio.emit("transcript_user", {"text": transcript}, room=_current_sid)

        elif etype == "response.function_call_arguments.done":
            if data.get("name") == "get_director_decision":
                threading.Thread(
                    target=handle_director_tool, args=(ws, data), daemon=True
                ).start()

        elif etype == "response.done":
            olaf_text = ""
            try:
                for item in data.get("response", {}).get("output", []):
                    for part in item.get("content", []):
                        txt = part.get("transcript") or part.get("text") or ""
                        olaf_text += txt
            except Exception:
                pass
            if olaf_text and _transcript:
                _transcript[-1]["character_response"] = olaf_text
                with _lock:
                    _state["story_so_far"] += f"\nOlaf: {olaf_text}\n"
            if _current_sid:
                socketio.emit("response_done", {}, room=_current_sid)

        elif etype == "error":
            print(f"[OpenAI error] {data}")
            if _current_sid:
                socketio.emit("error", {"message": str(data.get("error", data))}, room=_current_sid)

    def on_error(ws, error):
        print(f"[OpenAI WS error] {error}")

    def on_close(ws, code, msg):
        print(f"[OpenAI WS closed] {code} {msg}")
        global _openai_ws
        _openai_ws = None

    ws = websocket.WebSocketApp(
        f"wss://api.openai.com/v1/realtime?model={REALTIME_MODEL}",
        header={"Authorization": f"Bearer {api_key}"},
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    _openai_ws = ws
    ws.run_forever()


# ── Socket.IO event handlers ───────────────────────────────────────────────────

@socketio.on("connect")
def on_connect():
    print(f"[SocketIO] client connected: {request.sid}")


@socketio.on("disconnect")
def on_disconnect():
    global _openai_ws, _current_sid
    print(f"[SocketIO] client disconnected: {request.sid}")
    if _openai_ws:
        try:
            _openai_ws.close()
        except Exception:
            pass
        _openai_ws = None
    _current_sid = None


@socketio.on("start_session")
def on_start_session(data):
    global _current_sid, _openai_ws
    _current_sid = request.sid

    scenario_key = data.get("scenario", "")
    if scenario_key not in _SCENARIO_REGISTRY:
        emit("error", {"message": f"Unknown scenario: {scenario_key}"})
        return

    try:
        time_limit = float(data.get("time_limit", 5.0))
    except (TypeError, ValueError):
        time_limit = 5.0
    time_limit = max(1.0, min(time_limit, 60.0))

    reset_state(scenario_key, time_limit)

    if _openai_ws:
        try:
            _openai_ws.close()
        except Exception:
            pass
        _openai_ws = None

    t = threading.Thread(target=run_openai_ws, daemon=True)
    t.start()


@socketio.on("audio_input")
def on_audio_input(data):
    if _openai_ws:
        try:
            _openai_ws.send(json.dumps({
                "type": "input_audio_buffer.append",
                "audio": data["audio"],
            }))
        except Exception as e:
            print(f"[audio_input error] {e}")


@socketio.on("text_input")
def on_text_input(data):
    global _last_user_input
    text = data.get("text", "").strip()
    if not text or not _openai_ws:
        return
    _last_user_input = text
    with _lock:
        _state["story_so_far"] += f"\nUser: {text}"
    try:
        _openai_ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            },
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


@app.route("/scenarios", methods=["GET"])
def list_scenarios():
    result = []
    for k, label in AVAILABLE_SCENARIOS.items():
        sc = _SCENARIO_REGISTRY.get(k, {})
        result.append({"key": k, "label": label, "beat_count": len(sc.get("beats", []))})
    return jsonify(result)


@app.route("/time_status", methods=["GET"])
def time_status():
    if _monitor is None:
        return jsonify({"active": False})
    with _lock:
        beat_index = _state["beat_index"]
        beats = _state["beats"]
        time_limit = _state.get("time_limit", 5.0)
    safe_idx = min(beat_index, len(beats) - 1) if beats else 0
    temporal = _monitor.state(safe_idx, beats) if beats else {}
    return jsonify({
        "active": True,
        "time_limit_minutes": time_limit,
        "elapsed_seconds": temporal.get("elapsed_seconds", 0),
        "remaining_seconds": temporal.get("remaining_seconds", 0),
        "pacing_mode": temporal.get("pacing_mode", "normal"),
        "should_stop": _monitor.should_stop_for_time(),
        "beat_index": beat_index,
        "total_beats": len(beats),
    })


@app.route("/state", methods=["GET"])
def get_state():
    return jsonify(get_state_snapshot())


@app.route("/save_session", methods=["POST"])
def save_session():
    try:
        with _lock:
            scenario_name = _state.get("scenario_name", "unknown")
            story_topic = _state.get("story_topic", "")
            beat_index = _state["beat_index"]
            completed_beats = list(_state["completed_beats"])
            time_limit = _state.get("time_limit", 5.0)
            beats = _state["beats"]
        transcript_copy = list(_transcript)
        elapsed = _monitor.state(beat_index, beats).get("elapsed_seconds", 0) if _monitor else 0

        output = {
            "scenario": scenario_name,
            "story_topic": story_topic,
            "time_limit_minutes": time_limit,
            "elapsed_seconds": elapsed,
            "beats_completed": beat_index,
            "completed_beats": completed_beats,
            "saved_at": datetime.now().isoformat(),
            "turns": transcript_copy,
        }

        output_dir = os.path.join(REAL_TIME_DIR, "outputs")
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{scenario_name}_tc.json"
        path = os.path.join(output_dir, filename)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        print(f"[Session saved] {path} ({len(transcript_copy)} turns)")
        return jsonify({"saved": True, "path": path, "turns": len(transcript_copy)})

    except Exception as e:
        print(f"Save error: {e}")
        return jsonify({"saved": False, "error": str(e)})




if __name__ == "__main__":
    print(f"Time-Constrained Demo Server running at http://localhost:{PORT}")
    socketio.run(app, host="0.0.0.0", port=PORT, debug=False, allow_unsafe_werkzeug=True)
