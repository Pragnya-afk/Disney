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

REAL_TIME_DIR = os.path.dirname(os.path.abspath(__file__))
IMPLEMENTATION_DIR = os.path.join(os.path.dirname(REAL_TIME_DIR), "Disney", "Implementation")
if not os.path.isdir(IMPLEMENTATION_DIR):
    IMPLEMENTATION_DIR = os.path.join(os.path.dirname(REAL_TIME_DIR), "Implementation")
sys.path.insert(0, IMPLEMENTATION_DIR)
sys.path.insert(0, os.path.join(IMPLEMENTATION_DIR, "director_agent"))

load_dotenv(os.path.join(IMPLEMENTATION_DIR, ".env"))

from director_core import get_director_decision, last_character_opener, opener_guard_actor_text
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


app = Flask(__name__, static_folder="public")
app.config["SECRET_KEY"] = "olaf-secret"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
PORT = int(os.getenv("PORT", 3000))

DIRECTOR_MODEL = "gpt-4o-mini"
REALTIME_MODEL = "gpt-realtime"
AUDIO_SAMPLE_RATE = 24_000

api_key = os.getenv("OPENAI_API_KEY")
_openai_client = OpenAI(api_key=api_key)
olaf_fx = get_fx_chain(OLAF_AUDIOFX_CONFIG)

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

_state = {
    "beat_index": 0,
    "completed_beats": [],
    "story_so_far": "",
    "turns_in_current_beat": 0,
    "beats": [],
    "story_topic": "",
    "scenario_name": "",
}
_lock = threading.Lock()
_character = OLAF_CHARACTER
_transcript: list = []
_openai_ws = None
_current_sid = None
_last_user_input = ""


def reset_state(scenario_key: str = "olaf_anna_courtyard"):
    global _character, _transcript, _last_user_input
    scenario = _SCENARIO_REGISTRY[scenario_key]
    with _lock:
        _state["beats"] = scenario["beats"]
        _state["story_topic"] = scenario["story_topic"]
        _state["scenario_name"] = scenario_key
        _state["beat_index"] = 0
        _state["completed_beats"] = []
        _state["story_so_far"] = ""
        _state["turns_in_current_beat"] = 0
    _character = OLAF_CHARACTER
    _transcript = []
    _last_user_input = ""


def get_state_snapshot():
    with _lock:
        return dict(_state)


def build_system_prompt(state: dict) -> str:
    beats = state["beats"]
    idx = state["beat_index"]
    safe_idx = min(idx, len(beats) - 1)
    current_beat = beats[safe_idx]
    next_beat = beats[safe_idx + 1]["name"] if safe_idx < len(beats) - 1 else "None"
    story_tail = state["story_so_far"][-600:] if state["story_so_far"] else "(story just started)"

    return f"""
You are an interactive storytelling engine voicing {_character['name']}.
You speak AS {_character['name']}. Stay fully in character at all times.

CRITICAL: Before EVERY response you MUST call the get_director_decision tool.
Do not speak until you have received the director's instruction.
Use the returned director_instruction to guide exactly what you say.

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
        "Get the director's instruction for this story turn. "
        "Call this BEFORE every response. "
        "Use the returned director_instruction to guide what Olaf says."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "user_input": {"type": "string", "description": "What the user just said."}
        },
        "required": ["user_input"],
    },
}


def handle_director_tool(ws, event: dict):
    global _last_user_input
    args = json.loads(event.get("arguments", "{}"))
    user_input = args.get("user_input") or _last_user_input or "(no input)"

    with _lock:
        _state["turns_in_current_beat"] += 1
        state_snapshot = dict(_state)

    beats = state_snapshot["beats"]
    try:
        decision = get_director_decision(
            client=_openai_client,
            model=DIRECTOR_MODEL,
            user_input=user_input,
            story_state=state_snapshot,
            character=_character,
            story_topic=state_snapshot["story_topic"],
            beats=beats,
        )
    except Exception as e:
        print(f"[Director error] {e}")
        decision = {"director_instruction": "Continue the story naturally.", "decision_type": "progress_story"}

    safe_idx = min(state_snapshot["beat_index"], len(beats) - 1)
    current_beat = beats[safe_idx]
    next_beat = beats[safe_idx + 1]["name"] if safe_idx < len(beats) - 1 else "None"

    if decision.get("should_complete_beat"):
        with _lock:
            idx = _state["beat_index"]
            if idx < len(beats):
                _state["completed_beats"].append(beats[idx]["name"])
                _state["beat_index"] += 1
                _state["turns_in_current_beat"] = 0
                print(f"[Beat complete → beat {_state['beat_index']}]")

    # Update system prompt with latest state
    state_now = get_state_snapshot()
    ws.send(json.dumps({
        "type": "session.update",
        "session": {"type": "realtime", "instructions": build_system_prompt(state_now)},
    }))

    tool_result = {
        "director_instruction": decision.get("director_instruction", ""),
        "decision_type": decision.get("decision_type", "progress_story"),
        "current_beat": current_beat["name"],
        "current_beat_goal": current_beat["goal"],
        "next_beat": next_beat,
        "story_so_far_tail": state_snapshot["story_so_far"][-300:],
    }

    # Deterministically append the opener-diversity guard — the director LLM's
    # own free text has proven unreliable at restating this, so it's injected
    # here in plain code rather than left to the director's compliance.
    last_opener = last_character_opener(state_snapshot.get("story_so_far", ""))
    tool_result["director_instruction"] = (
        f"{tool_result['director_instruction']}\n\n[OPENER GUARD] {opener_guard_actor_text(last_opener)}"
    )

    print(f"[Director: {decision.get('decision_type')}] {decision.get('director_instruction', '')[:60]}...")

    if _current_sid:
        with _lock:
            current_beat_index = _state["beat_index"]
            total_beats = len(_state["beats"])
        socketio.emit("director_decision", {
            "decision_type": decision.get("decision_type"),
            "instruction": decision.get("director_instruction", "")[:80],
            "beat_index": current_beat_index,
            "total_beats": total_beats,
        }, room=_current_sid)

    _transcript.append({
        "turn": len(_transcript) + 1,
        "beat": current_beat["name"],
        "user_input": user_input,
        "director_decision": decision,
        "character_response": "",
    })

    # Send tool result and trigger response
    ws.send(json.dumps({
        "type": "conversation.item.create",
        "item": {
            "type": "function_call_output",
            "call_id": event["call_id"],
            "output": json.dumps(tool_result),
        },
    }))
    ws.send(json.dumps({"type": "response.create"}))



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
                with _lock:
                    beats_payload = list(_state.get("beats", []))
                socketio.emit("session_started", {
                    "scenario": _state.get("scenario_name", ""),
                    "beats": beats_payload,
                    "beat_index": _state.get("beat_index", 0),
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
            # Extract Olaf's text from done event to update story
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
        header={
            "Authorization": f"Bearer {api_key}",
        },
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    _openai_ws = ws
    ws.run_forever()



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

    scenario_key = data.get("scenario", "olaf_anna_courtyard")
    if scenario_key not in _SCENARIO_REGISTRY:
        scenario_key = "olaf_anna_courtyard"
    reset_state(scenario_key)

    # Close any existing OpenAI WS
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



@app.route("/")
def index():
    return send_from_directory("public", "index.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory("public", path)


@app.route("/scenarios", methods=["GET"])
def list_scenarios():
    result = []
    for k, v in AVAILABLE_SCENARIOS.items():
        sc = _SCENARIO_REGISTRY.get(k, {})
        result.append({"key": k, "label": v, "beat_count": len(sc.get("beats", []))})
    return jsonify(result)


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
        transcript_copy = list(_transcript)

        output = {
            "scenario": scenario_name,
            "story_topic": story_topic,
            "beats_completed": beat_index,
            "completed_beats": completed_beats,
            "saved_at": datetime.now().isoformat(),
            "turns": transcript_copy,
        }

        output_dir = os.path.join(REAL_TIME_DIR, "outputs")
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{scenario_name}.json"
        path = os.path.join(output_dir, filename)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        print(f"[Session saved] {path} ({len(transcript_copy)} turns)")
        return jsonify({"saved": True, "path": path, "turns": len(transcript_copy)})

    except Exception as e:
        print(f"Save error: {e}")
        return jsonify({"saved": False, "error": str(e)})




if __name__ == "__main__":
    print(f"Server running at http://localhost:{PORT}")
    socketio.run(app, host="0.0.0.0", port=PORT, debug=False, allow_unsafe_werkzeug=True)
