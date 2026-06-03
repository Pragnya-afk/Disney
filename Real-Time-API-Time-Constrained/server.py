import os
import sys
import json
import time
import threading
import requests
from datetime import datetime
from flask import Flask, request, Response, send_from_directory, jsonify
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ── Path setup ─────────────────────────────────────────────────────────────────
REAL_TIME_DIR = os.path.dirname(os.path.abspath(__file__))
IMPLEMENTATION_DIR = os.path.join(os.path.dirname(REAL_TIME_DIR), "Disney", "Implementation")
if not os.path.isdir(IMPLEMENTATION_DIR):
    IMPLEMENTATION_DIR = os.path.join(os.path.dirname(REAL_TIME_DIR), "Implementation")
sys.path.insert(0, IMPLEMENTATION_DIR)
sys.path.insert(0, os.path.join(IMPLEMENTATION_DIR, "director_agent"))
sys.path.insert(0, os.path.join(IMPLEMENTATION_DIR, "director_agent", "time_constrained"))

# Also try loading .env from Implementation folder
load_dotenv(os.path.join(IMPLEMENTATION_DIR, ".env"))

import importlib
import glob
from time_director_core import get_time_director_decision
from time_control import TemporalMonitor
from character_prompts.olaf import CHARACTER as OLAF_CHARACTER
from scenarios.olaf_derailment_scenario_suite import NO_DERAILMENT_SCENARIOS

# ── Config ─────────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder="public")
PORT = int(os.getenv("PORT", 3001))

DIRECTOR_MODEL = "gpt-4o-mini"
REALTIME_MODEL = "gpt-realtime"

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ── Scenario registry ──────────────────────────────────────────────────────────
_SUITE_FILE = "olaf_derailment_scenario_suite"
_SKIP_FILES = {_SUITE_FILE, "__init__"}
_SKIP_PATTERNS = ("medium_derail", "complete_derail")


def _make_label(key: str) -> str:
    label = key.replace("_no_derailment", "").replace("_", " ")
    return " ".join(w.capitalize() for w in label.split())


def _build_registry() -> dict[str, dict]:
    registry: dict[str, dict] = {}

    pattern = os.path.join(IMPLEMENTATION_DIR, "scenarios", "*.py")
    for path in sorted(glob.glob(pattern)):
        module_name = os.path.splitext(os.path.basename(path))[0]
        if (module_name in _SKIP_FILES
                or module_name.startswith("_")
                or any(p in module_name for p in _SKIP_PATTERNS)):
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
AVAILABLE_SCENARIOS: dict[str, str] = {k: _make_label(k) for k in _SCENARIO_REGISTRY}

# ── Story state (one session at a time) ───────────────────────────────────────
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
_transcript: list[dict] = []


def load_scenario(scenario_key: str) -> None:
    global _character
    scenario = _SCENARIO_REGISTRY[scenario_key]
    with _lock:
        _state["beats"] = scenario["beats"]
        _state["story_topic"] = scenario["story_topic"]
        _state["scenario_name"] = scenario_key
    _character = OLAF_CHARACTER


def reset_state(scenario_key: str = "olaf_anna_courtyard", time_limit: float = 5.0) -> None:
    global _monitor, _transcript
    load_scenario(scenario_key)
    with _lock:
        _state["beat_index"] = 0
        _state["completed_beats"] = []
        _state["story_so_far"] = ""
        _state["turns_in_current_beat"] = 0
        _state["time_limit"] = time_limit
    _transcript = []
    _monitor = TemporalMonitor(
        time_limit_minutes=time_limit,
        total_beats=len(_state["beats"]),
    )


def get_state_snapshot() -> dict:
    with _lock:
        return {k: v for k, v in _state.items()}


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
- too_fast: story is ahead of schedule — expand the current beat with detail, emotion, suspense. Do NOT rush to the next beat.
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


# ── Director tool schema ───────────────────────────────────────────────────────
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
            "user_input": {
                "type": "string",
                "description": "What the user just said.",
            }
        },
        "required": ["user_input"],
    },
}


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("public", "index.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory("public", path)


@app.route("/scenarios", methods=["GET"])
def list_scenarios():
    return jsonify([{"key": k, "label": v} for k, v in AVAILABLE_SCENARIOS.items()])


@app.route("/session", methods=["POST"])
def create_session():
    try:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return Response("Missing OPENAI_API_KEY", status=500)

        scenario_key = request.args.get("scenario", "olaf_anna_courtyard")
        if scenario_key not in AVAILABLE_SCENARIOS:
            scenario_key = "olaf_anna_courtyard"

        try:
            time_limit = float(request.args.get("time_limit", "5"))
        except ValueError:
            time_limit = 5.0
        time_limit = max(1.0, min(time_limit, 60.0))

        reset_state(scenario_key, time_limit)
        state = get_state_snapshot()

        sdp_offer = request.data.decode("utf-8")

        session_config = {
            "type": "realtime",
            "model": REALTIME_MODEL,
            "instructions": build_system_prompt(state),
            "audio": {
                "input": {
                    "transcription": {"model": "whisper-1"},
                    "turn_detection": {
                        "type": "server_vad",
                        "silence_duration_ms": 700,
                        "threshold": 0.5,
                    },
                },
                "output": {"voice": "coral"},
            },
            "tools": [DIRECTOR_TOOL],
            "tool_choice": "auto",
        }

        files = {
            "sdp": (None, sdp_offer),
            "session": (None, json.dumps(session_config)),
        }

        response = requests.post(
            "https://api.openai.com/v1/realtime/calls",
            headers={"Authorization": f"Bearer {api_key}"},
            files=files,
        )

        if not response.ok:
            print("OpenAI error:", response.text)
            return Response(response.text, status=response.status_code)

        return Response(response.text, status=200, content_type="application/sdp")

    except Exception as e:
        print("Session error:", e)
        return Response("Failed to create session", status=500)


@app.route("/director", methods=["POST"])
def director():
    """Run the time-constrained director agent and return its decision."""
    try:
        data = request.get_json()
        user_input = data.get("user_input", "")

        with _lock:
            _state["turns_in_current_beat"] += 1
            state_snapshot = {k: v for k, v in _state.items()}

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

        decision = get_time_director_decision(
            client=client,
            model=DIRECTOR_MODEL,
            user_input=user_input,
            story_state=state_snapshot,
            character=_character,
            story_topic=state_snapshot["story_topic"],
            beats=beats,
            temporal_state=temporal_state,
        )

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

        pacing_mode = temporal_state.get("pacing_mode", "normal")

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

        print(
            f"[Director: {decision.get('decision_type')} | Pacing: {pacing_mode} | "
            f"Remaining: {temporal_state.get('remaining_seconds', 0):.0f}s] "
            f"{decision.get('director_instruction', '')[:60]}..."
        )

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

        return jsonify({
            "tool_result": tool_result,
            "should_complete_beat": decision.get("should_complete_beat", False),
            "pacing_mode": pacing_mode,
            "elapsed_seconds": temporal_state.get("elapsed_seconds", 0),
            "remaining_seconds": temporal_state.get("remaining_seconds", 0),
        })

    except Exception as e:
        print("Director error:", e)
        return jsonify({
            "tool_result": {
                "director_instruction": "Continue the story naturally.",
                "pacing_mode": "normal",
                "elapsed_seconds": 0,
                "remaining_seconds": 0,
            },
            "error": str(e),
        })


@app.route("/time_status", methods=["GET"])
def time_status():
    """Returns current temporal state for the browser countdown timer."""
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


@app.route("/story_update", methods=["POST"])
def story_update():
    """Called by the browser after each turn to update story_so_far."""
    try:
        data = request.get_json()
        user_text = data.get("user_text", "")
        olaf_text = data.get("olaf_text", "")

        with _lock:
            if user_text:
                _state["story_so_far"] += f"\nUser: {user_text}"
            if olaf_text:
                _state["story_so_far"] += f"\nOlaf: {olaf_text}\n"

        if olaf_text and _transcript:
            _transcript[-1]["character_response"] = olaf_text

        return jsonify({"ok": True, "beat_index": _state["beat_index"]})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/state", methods=["GET"])
def get_state():
    """Debug endpoint — current story state."""
    return jsonify(get_state_snapshot())


@app.route("/save_session", methods=["POST"])
def save_session():
    """Save the current session transcript to outputs/."""
    try:
        with _lock:
            scenario_name = _state.get("scenario_name", "unknown")
            story_topic = _state.get("story_topic", "")
            beat_index = _state["beat_index"]
            completed_beats = list(_state["completed_beats"])
            time_limit = _state.get("time_limit", 5.0)
        transcript_copy = list(_transcript)

        elapsed = _monitor.state(beat_index, _state["beats"]).get("elapsed_seconds", 0) if _monitor else 0

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
    print(f"Time-Constrained Realtime Story Server running at http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=True)
