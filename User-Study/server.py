import os, sys, json, threading, random, time
from dataclasses import dataclass, field
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

from director_core import (
    get_director_decision, last_character_opener, opener_guard_actor_text, strip_banned_opener,
)
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
STORY_2_KEY = "olaf_retells_cinderella_no_derailment"
STORY_1_TIME_LIMIT = 5.0   # minutes — frontend-enforced hard cutoff
STORY_2_TIME_LIMIT = 5.0   # minutes — server-enforced
AUTO_ADVANCE_SECONDS = 60

_SCENARIO_REGISTRY = {sc["scenario_name"]: sc for sc in NO_DERAILMENT_SCENARIOS}

app = Flask(__name__, static_folder="public")
app.config["SECRET_KEY"] = "olaf-study-2026"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

DIRECTOR_MODEL = "gpt-4o-mini"
REALTIME_MODEL = "gpt-realtime"

api_key = os.getenv("OPENAI_API_KEY")
_client = OpenAI(api_key=api_key)


#  Per-participant session state 
# Everything a single participant's run through the study needs, isolated per
# Socket.IO connection so concurrent participants never see each other's
# story state, transcripts, timers, or output files.
@dataclass(eq=False)
class Session:
    sid: str
    lock: threading.Lock = field(default_factory=threading.Lock)   # guards `state` only

    story1_order: list = field(default_factory=list)   # ["baseline","director"] or ["director","baseline"]
    story2_order: list = field(default_factory=list)   # ["director","time_constrained"] or ["time_constrained","director"]
    study_phase: int = 0   # 0=idle  1=story1_r1  2=story1_r2  3=story2_r1  4=story2_r2
    study_output: dict = field(default_factory=dict)
    session_file_path: "str | None" = None

    state: dict = field(default_factory=lambda: {
        "beat_index": 0, "completed_beats": [], "story_so_far": "",
        "turns_in_current_beat": 0, "expansion_index": 0,
        "beats": [], "story_topic": "", "scenario_name": "", "time_limit": 5.0,
    })
    transcript: list = field(default_factory=list)
    monitor: "TemporalMonitor | None" = None
    openai_ws: "websocket.WebSocketApp | None" = None

    last_user_input: str = ""
    last_user_activity_ts: float = 0.0
    time_up_injected: bool = False

    auto_advance_timer: "threading.Timer | None" = None
    wall_timer: "threading.Timer | None" = None

    def condition(self, phase: int) -> str:
        if phase == 1: return self.story1_order[0] if self.story1_order else "baseline"
        if phase == 2: return self.story1_order[1] if self.story1_order else "director"
        if phase == 3: return self.story2_order[0] if self.story2_order else "director"
        if phase == 4: return self.story2_order[1] if self.story2_order else "time_constrained"
        return "director"

    def story_num(self, phase: int) -> int:
        return 1 if phase <= 2 else 2

    def round_num(self, phase: int) -> int:
        return 1 if phase in (1, 3) else 2

    def scenario_key(self, phase: int) -> str:
        return STORY_1_KEY if phase <= 2 else STORY_2_KEY

    def time_limit_for(self, phase: int) -> float:
        return STORY_1_TIME_LIMIT if phase <= 2 else STORY_2_TIME_LIMIT

    def snapshot(self) -> dict:
        with self.lock:
            return dict(self.state)


_sessions: dict[str, Session] = {}
_sessions_lock = threading.Lock()


def _create_session(sid: str) -> Session:
    sess = Session(sid=sid)
    with _sessions_lock:
        _sessions[sid] = sess
    return sess


def _get_session(sid) -> "Session | None":
    if not sid:
        return None
    with _sessions_lock:
        return _sessions.get(sid)


def _remove_session(sid: str) -> "Session | None":
    with _sessions_lock:
        return _sessions.pop(sid, None)


def build_prompt(sess: Session, state: dict) -> str:
    cond = sess.condition(sess.study_phase)
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


def _handle_baseline_input(sess: Session, text: str):
    """Call baseline/main.py directly — no director, just Olaf."""
    with sess.lock:
        snap = dict(sess.state)
        sess.state["story_so_far"] += f"\nUser: {text}"

    beats = snap["beats"]
    current_beat_name = beats[min(snap["beat_index"], len(beats) - 1)]["name"]

    prompt = baseline_build_prompt(text, OLAF_CHARACTER, beats, snap.get("story_so_far", ""))

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

    with sess.lock:
        sess.state["story_so_far"] += f"\nOlaf: {olaf_text}\n"
        sess.state["turns_in_current_beat"] = snap.get("turns_in_current_beat", 0) + 1
        if beat_completed and snap["beat_index"] < len(beats):
            sess.state["completed_beats"].append(beats[snap["beat_index"]]["name"])
            sess.state["beat_index"] += 1
            sess.state["turns_in_current_beat"] = 0
            print(f"[Baseline beat → {sess.state['beat_index']} (model)]")

    sess.transcript.append({
        "turn": len(sess.transcript) + 1,
        "beat": current_beat_name,
        "user_input": text,
        "character_response": olaf_text,
        "model_output": output,
        "condition": "baseline",
    })

    if sess.sid:
        socketio.emit("transcript_assistant", {"delta": olaf_text}, room=sess.sid)
        socketio.emit("response_done", {}, room=sess.sid)

    _schedule_auto_advance(sess)


def _director_prompt(state: dict, timed: bool, current_instruction: str = "") -> str:
    beats = state["beats"]
    idx = state["beat_index"]
    si = min(idx, len(beats) - 1)
    cb = beats[si]
    nb = beats[si + 1]["name"] if si < len(beats) - 1 else "None"
    tail = state["story_so_far"][-600:] if state["story_so_far"] else "(story just started)"
    tl = state.get("time_limit", 5.0)
    instruction_block = f"""
## Director Instruction For This Turn (MANDATORY — follow exactly, including any [OPENER GUARD] line)
{current_instruction}
""" if current_instruction else ""

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
- Keep responses short: 3–5 sentences, natural when read.
- The director_instruction in the tool result is mandatory — realize it.
- Vary tone: sometimes excited, sometimes curious, sometimes gentle.
- Do not start most turns with "Oh". Do not repeat the same phrases.
{pacing}{instruction_block}
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


def _cancel_auto_advance(sess: Session):
    if sess.auto_advance_timer:
        sess.auto_advance_timer.cancel()
        sess.auto_advance_timer = None


def _schedule_auto_advance(sess: Session):
    _cancel_auto_advance(sess)

    def _fire():
        if not sess.sid:
            return
        # threading.Timer.cancel() cannot stop a timer whose callback has
        # already started running — if the user's real input lands in that
        # narrow window, _cancel_auto_advance() (called from on_text_input)
        # is a no-op and this still fires. Re-validate idle time here so a
        # stale fire backs off instead of racing a real user turn: sending
        # two concurrent response.create calls on the same Realtime session
        # gets the second one rejected, silently dropping that turn (no
        # director_decision, no character response, no transcript entry).
        idle_for = time.time() - sess.last_user_activity_ts
        if idle_for < AUTO_ADVANCE_SECONDS - 1:
            _schedule_auto_advance(sess)
            return
        cond = sess.condition(sess.study_phase)
        if cond == "baseline":
            threading.Thread(
                target=_handle_baseline_input,
                args=(sess, "[The user is listening — continue the story naturally]"),
                daemon=True,
            ).start()
            return
        if not sess.openai_ws:
            # Connection dropped — keep polling instead of letting the heartbeat
            # die permanently, so the story can resume if the socket recovers.
            _schedule_auto_advance(sess)
            return
        with sess.lock:
            sess.state["story_so_far"] += "\nUser: (no response)"
        try:
            sess.openai_ws.send(json.dumps({
                "type": "conversation.item.create",
                "item": {"type": "message", "role": "user",
                         "content": [{"type": "input_text",
                                      "text": "[The user is listening — continue the story naturally]"}]},
            }))
            sess.openai_ws.send(json.dumps({"type": "response.create", "response": {"tool_choice": "required"}}))
        except Exception as e:
            print(f"[auto-advance error] {e}")
            return
        _schedule_auto_advance(sess)

    sess.auto_advance_timer = threading.Timer(AUTO_ADVANCE_SECONDS, _fire)
    sess.auto_advance_timer.daemon = True
    sess.auto_advance_timer.start()


def _start_wall_timer(sess: Session, time_limit_minutes: float):
    _cancel_wall_timer(sess)

    def _fire():
        if not sess.time_up_injected:
            sess.time_up_injected = True
            if sess.sid:
                socketio.emit("time_up", {}, room=sess.sid)
        threading.Thread(target=_auto_finish_active_phase, args=(sess,), daemon=True).start()

    sess.wall_timer = threading.Timer(time_limit_minutes * 60, _fire)
    sess.wall_timer.daemon = True
    sess.wall_timer.start()


def _cancel_wall_timer(sess: Session):
    if sess.wall_timer:
        try:
            sess.wall_timer.cancel()
        except Exception:
            pass
        sess.wall_timer = None


def reset_story(sess: Session, phase: int):
    cond = sess.condition(phase)
    sc = _SCENARIO_REGISTRY[sess.scenario_key(phase)]
    tl = sess.time_limit_for(phase)

    with sess.lock:
        sess.state.update({
            "beats": sc["beats"], "story_topic": sc["story_topic"],
            "scenario_name": sess.scenario_key(phase), "beat_index": 0,
            "completed_beats": [], "story_so_far": "",
            "turns_in_current_beat": 0, "expansion_index": 0,
            "time_limit": tl,
        })
    sess.transcript = []
    sess.last_user_input = ""
    sess.last_user_activity_ts = time.time()
    sess.time_up_injected = False
    _cancel_auto_advance(sess)
    _cancel_wall_timer(sess)
    sess.monitor = None

    if phase in (3, 4):
        if cond == "time_constrained":
            final_buffer = 55.0
            sess.monitor = TemporalMonitor(
                time_limit_minutes=tl,
                total_beats=len(sc["beats"]),
                final_buffer_seconds=final_buffer,
            )
            # Backstop: the "final" pacing wrap-up only runs on the turn/tool-call
            # cycle, which depends on the auto-advance heartbeat staying alive.
            # If that heartbeat dies (e.g. the realtime websocket drops without
            # reconnecting), no further turns ever fire and the phase would
            # otherwise hang until the participant disconnects — see the
            # session that ran 942s over a 300s budget before being marked
            # abandoned. Force-finish shortly after the buffer window closes so
            # the phase is always saved close to the time budget regardless.
            _start_wall_timer(sess, tl + (final_buffer + 60) / 60)
        else:
            _start_wall_timer(sess, tl)


def handle_director_tool(sess: Session, ws, event: dict):
    if sess.openai_ws is not ws:
        return   # stale callback from a websocket this session has since replaced

    cond = sess.condition(sess.study_phase)
    args = json.loads(event.get("arguments", "{}"))
    user_input = args.get("user_input") or sess.last_user_input or "(no input)"

    with sess.lock:
        sess.state["turns_in_current_beat"] += 1
        snap = dict(sess.state)

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
            with sess.lock:
                idx = sess.state["beat_index"]
                if idx < len(beats):
                    sess.state["completed_beats"].append(beats[idx]["name"])
                    sess.state["beat_index"] += 1
                    sess.state["turns_in_current_beat"] = 0
                    print(f"[Beat → {sess.state['beat_index']}]")

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
        temporal = sess.monitor.state(si, beats) if sess.monitor else {
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
        next_high_idx = None
        if pacing_mode == "too_fast":
            decision["should_complete_beat"] = False
            exps = cb.get("expansions", [])
            ei = snap.get("expansion_index", 0)
            if ei < len(exps):
                suggested_exp = exps[ei]
                with sess.lock:
                    sess.state["expansion_index"] = ei + 1
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
            sess.time_up_injected = True
            if sess.sid:
                socketio.emit("time_up", {}, room=sess.sid)
        elif pacing_mode == "hurry":
            if snap.get("turns_in_current_beat", 0) >= 2:
                decision["should_complete_beat"] = True
                decision["director_instruction"] = (
                    decision.get("director_instruction", "") + " Wrap up this beat now and move on."
                )
        elif pacing_mode == "critical":
            decision["should_complete_beat"] = True
            next_high_idx = next(
                (i for i in range(si + 1, len(beats)) if beats[i].get("importance") == "high"), None
            )
            if next_high_idx is not None:
                next_high = beats[next_high_idx]
                decision["director_instruction"] = (
                    decision.get("director_instruction", "") +
                    f" Bridge immediately to: {next_high['name']} — {next_high['goal']}"
                )

        if decision.get("should_complete_beat"):
            with sess.lock:
                idx = sess.state["beat_index"]
                if pacing_mode == "final":
                    target = len(beats)
                elif pacing_mode == "critical" and next_high_idx is not None:
                    target = next_high_idx
                else:
                    target = idx + 1
                target = min(target, len(beats))
                if idx < target:
                    sess.state["completed_beats"].extend(b["name"] for b in beats[idx:target])
                    sess.state["beat_index"] = target
                sess.state["turns_in_current_beat"] = 0
                sess.state["expansion_index"] = 0
                print(f"[Beat → {sess.state['beat_index']} | {pacing_mode}]")

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

    # Deterministically append the opener-diversity guard — the director LLM's
    # own free text has proven unreliable at restating this, so it's injected
    # here in plain code rather than left to the director's compliance.
    last_opener = last_character_opener(snap.get("story_so_far", ""))
    tool_result["director_instruction"] = (
        f"{tool_result.get('director_instruction', '')}\n\n[OPENER GUARD] {opener_guard_actor_text(last_opener)}"
    )

   
    snap_now = sess.snapshot()
    instructions = _director_prompt(
        snap_now, timed=(cond == "time_constrained"),
        current_instruction=tool_result["director_instruction"],
    )
    ws.send(json.dumps({
        "type": "session.update",
        "session": {"type": "realtime", "instructions": instructions},
    }))

    if sess.sid:
        socketio.emit("director_decision", emit_data, room=sess.sid)

    entry = {
        "turn": len(sess.transcript) + 1,
        "beat": cb["name"],
        "user_input": user_input,
        "director_decision": decision,
        "pacing_mode": pacing_mode,
        "character_response": "",
    }
    if temporal:
        entry["elapsed_seconds"] = temporal.get("elapsed_seconds", 0)
        entry["remaining_seconds"] = temporal.get("remaining_seconds", 0)
    sess.transcript.append(entry)

    ws.send(json.dumps({
        "type": "conversation.item.create",
        "item": {
            "type": "function_call_output",
            "call_id": event["call_id"],
            "output": json.dumps(tool_result),
        },
    }))
    ws.send(json.dumps({"type": "response.create"}))

    if (cond == "time_constrained" and sess.monitor
            and sess.monitor.should_stop_for_time() and not sess.time_up_injected):
        sess.time_up_injected = True
        if sess.sid:
            socketio.emit("time_up", {}, room=sess.sid)
        ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message", "role": "user",
                "content": [{"type": "input_text",
                             "text": "[Story time ended — wrap up all remaining beats with a complete, satisfying ending]"}],
            },
        }))
        ws.send(json.dumps({"type": "response.create"}))


def _write_session_file(sess: Session):
    if not sess.session_file_path:
        return
    try:
        with open(sess.session_file_path, "w", encoding="utf-8") as f:
            json.dump(sess.study_output, f, indent=2, ensure_ascii=False)
        print(f"[Study] Session file updated → {sess.session_file_path}")
    except Exception as e:
        print(f"[write_session_file error] {e}")


def _save_phase_data(sess: Session, phase: int, transcript_copy: list, snap: dict,
                     elapsed: float = 0, abandoned: bool = False) -> None:
    cond = sess.condition(phase)
    phase_data = {
        "condition": cond,
        "story": sess.story_num(phase),
        "round": sess.round_num(phase),
        "scenario": snap.get("scenario_name", ""),
        "story_topic": snap.get("story_topic", ""),
        "beats_completed": snap["beat_index"],
        "completed_beats": snap["completed_beats"],
        "elapsed_seconds": round(elapsed, 2),
        "time_limit_minutes": sess.time_limit_for(phase),
        "turns": transcript_copy,
    }
    if abandoned:
        phase_data["abandoned"] = True

    sess.study_output.setdefault("phases", {})[str(phase)] = phase_data
    _write_session_file(sess)
    print(f"[Study] Phase {phase} ({cond}) saved to session file")


def _save_abandoned_if_active(sess: Session) -> None:
    """Persist partial progress for a participant who disconnected or restarted mid-study."""
    if not (sess.study_output and sess.study_phase > 0):
        return
    try:
        with sess.lock:
            snap = dict(sess.state)
        transcript_copy = list(sess.transcript)
        elapsed = 0
        if sess.monitor:
            try:
                elapsed = sess.monitor.elapsed_seconds()
            except Exception:
                pass
        sess.study_output["abandoned_at_phase"] = sess.study_phase
        if transcript_copy or snap.get("story_so_far"):
            _save_phase_data(sess, sess.study_phase, transcript_copy, snap, elapsed, abandoned=True)
        else:
            _write_session_file(sess)
    except Exception as e:
        print(f"[abandon save error] {e}")


def _auto_finish_active_phase(sess: Session):
    import time as _time
    _time.sleep(1.0)
    phase = sess.study_phase
    with sess.lock:
        snap = dict(sess.state)
    transcript_copy = list(sess.transcript)
    elapsed = 0
    if sess.monitor:
        try:
            elapsed = sess.monitor.elapsed_seconds()
        except Exception:
            pass
    _save_phase_data(sess, phase, transcript_copy, snap, elapsed)
    print(f"[Study] Phase {phase} auto-finished ({len(transcript_copy)} turns)")
    if sess.sid:
        socketio.emit("story_finished", {"phase": phase, "turns": len(transcript_copy)}, room=sess.sid)
    close_ws(sess)


def run_openai_ws(sess: Session):
    def on_open(ws):
        cond = sess.condition(sess.study_phase)
        state = sess.snapshot()
        session_cfg = {
            "type": "realtime",
            "output_modalities": ["text"],
            "instructions": build_prompt(sess, state),
            "tool_choice": "auto",
        }
        if cond != "baseline":
            session_cfg["tools"] = [DIRECTOR_TOOL]
        ws.send(json.dumps({"type": "session.update", "session": session_cfg}))
        print(f"[WS] connected (phase {sess.study_phase}, condition {cond})")

    def on_message(ws, message):
        try:
            data = json.loads(message)
        except Exception:
            return
        etype = data.get("type", "")

        if etype == "session.created":
            if sess.sid:
                socketio.emit("session_started", {"phase": sess.study_phase}, room=sess.sid)

        elif etype in ("response.text.delta", "response.audio_transcript.delta",
                       "response.output_audio_transcript.delta"):
            delta = data.get("delta", "")
            if delta and sess.sid:
                socketio.emit("transcript_assistant", {"delta": delta}, room=sess.sid)

        elif etype == "response.function_call_arguments.done":
            if data.get("name") == "get_director_decision":
                threading.Thread(target=handle_director_tool, args=(sess, ws, data), daemon=True).start()

        elif etype == "response.done":
            cond = sess.condition(sess.study_phase)
            olaf_text = ""
            try:
                for item in data.get("response", {}).get("output", []):
                    for part in item.get("content", []):
                        olaf_text += part.get("transcript") or part.get("text") or ""
            except Exception:
                pass

            if olaf_text:
                with sess.lock:
                    if cond != "baseline":
                        # The prompt-level opener guard is unreliable in practice —
                        # the actor model keeps reusing "Oh"/"Ooh" turn after turn
                        # despite the instruction. Deterministically strip a repeated
                        # filler opener here rather than trusting compliance.
                        prior_opener = last_character_opener(sess.state["story_so_far"])
                        olaf_text = strip_banned_opener(olaf_text, prior_opener)
                    sess.state["story_so_far"] += f"\nOlaf: {olaf_text}\n"
                if cond == "baseline":
                    # Baseline uses WebSocket fallback path (shouldn't reach here normally)
                    sess.transcript.append({
                        "turn": len(sess.transcript) + 1,
                        "user_input": sess.last_user_input or "(auto-advance)",
                        "character_response": olaf_text,
                        "condition": "baseline",
                    })
                elif sess.transcript:
                    sess.transcript[-1]["character_response"] = olaf_text
                # gpt-realtime sends full text in response.done, not via text.delta events
                if sess.sid:
                    socketio.emit("transcript_assistant", {"delta": olaf_text}, room=sess.sid)

            if sess.sid:
                socketio.emit("response_done", {}, room=sess.sid)
            _schedule_auto_advance(sess)

            # One "final" turn produces two response.done events: the tool
            # call itself (no text) fires first, then the actual closing
            # narration (real text) fires later once handle_director_tool's
            # own response.create resolves. Only auto-finish on the one that
            # actually delivered text — otherwise this can race and tear
            # down the connection (close_ws) before the wrap-up ever streams
            # back, since time_up_injected is set synchronously as soon as
            # pacing_mode hits "final", before either response.done arrives.
            if sess.study_phase in (3, 4) and sess.time_up_injected and olaf_text:
                threading.Thread(target=_auto_finish_active_phase, args=(sess,), daemon=True).start()

        elif etype == "error":
            print(f"[OpenAI error] {data}")
            if sess.sid:
                socketio.emit("error", {"message": str(data.get("error", data))}, room=sess.sid)

    def on_error(ws, err):
        print(f"[WS error] {err}")

    def on_close(ws, code, msg):
        print(f"[WS closed] {code}")
        if sess.openai_ws is ws:
            sess.openai_ws = None

    ws = websocket.WebSocketApp(
        f"wss://api.openai.com/v1/realtime?model={REALTIME_MODEL}",
        header={"Authorization": f"Bearer {api_key}"},
        on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close,
    )
    sess.openai_ws = ws
    ws.run_forever()


def close_ws(sess: Session):
    if sess.openai_ws:
        try:
            sess.openai_ws.close()
        except Exception:
            pass
        sess.openai_ws = None


@socketio.on("connect")
def on_connect():
    _create_session(request.sid)
    # The client's own socket.id does not reliably match request.sid on this
    # Flask-SocketIO/python-socketio version — tell the client its real
    # session key explicitly so /state and /time_status lookups resolve.
    emit("server_sid", {"sid": request.sid})
    print(f"[SIO] connected: {request.sid}")


@socketio.on("disconnect")
def on_disconnect():
    print(f"[SIO] disconnected: {request.sid}")
    sess = _get_session(request.sid)
    if sess:
        close_ws(sess)
        _cancel_auto_advance(sess)
        _cancel_wall_timer(sess)
        _save_abandoned_if_active(sess)
        _remove_session(request.sid)


@socketio.on("begin_study")
def on_begin_study(_data):
    sess = _get_session(request.sid)
    if not sess:
        return
    sess.study_phase = 0
    sess.story1_order = random.sample(["baseline", "director"], 2)
    sess.story2_order = random.sample(["director", "time_constrained"], 2)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    subfolder = os.path.join(STUDY_DIR, "outputs")
    os.makedirs(subfolder, exist_ok=True)
    sess.session_file_path = os.path.join(subfolder, f"session_{ts}_{sess.sid[:8]}.json")

    sess.study_output = {
        "study_date": datetime.now().isoformat(),
        "story1_order": sess.story1_order,
        "story2_order": sess.story2_order,
        "phases": {},
    }
    _write_session_file(sess)
    emit("study_ready", {
        "story1_order": sess.story1_order,
        "story2_order": sess.story2_order,
    })
    print(f"[Study] Randomized — S1: {sess.story1_order}  S2: {sess.story2_order}  file: {sess.session_file_path}")


@socketio.on("start_phase")
def on_start_phase(data):
    sess = _get_session(request.sid)
    if not sess:
        return
    phase = data.get("phase")
    if phase not in (1, 2, 3, 4):
        return
    sess.study_phase = phase
    close_ws(sess)
    reset_story(sess, phase)
    cond = sess.condition(phase)
    if cond == "baseline":
        # Baseline uses regular chat API — no Realtime WebSocket needed.
        emit("session_started", {"phase": phase})
        _schedule_auto_advance(sess)
    else:
        threading.Thread(target=run_openai_ws, args=(sess,), daemon=True).start()
    print(f"[Study] Phase {phase} started (condition: {cond})")


@socketio.on("finish_story")
def on_finish_story(data):
    sess = _get_session(request.sid)
    if not sess:
        return
    phase = data.get("phase", sess.study_phase)
    close_ws(sess)
    _cancel_auto_advance(sess)
    _cancel_wall_timer(sess)

    with sess.lock:
        snap = dict(sess.state)
    transcript_copy = list(sess.transcript)
    elapsed = 0
    if sess.monitor:
        try:
            elapsed = sess.monitor.elapsed_seconds()
        except Exception:
            pass

    _save_phase_data(sess, phase, transcript_copy, snap, elapsed)
    emit("story_finished", {"phase": phase, "turns": len(transcript_copy)})


@socketio.on("cancel_study")
def on_cancel_study(_data):
    sess = _get_session(request.sid)
    if not sess:
        return
    print(f"[cancel_study] participant restarted: {request.sid}")
    close_ws(sess)
    _cancel_auto_advance(sess)
    _cancel_wall_timer(sess)
    _save_abandoned_if_active(sess)
    sess.study_phase = 0


@socketio.on("text_input")
def on_text_input(data):
    sess = _get_session(request.sid)
    if not sess:
        return
    text = data.get("text", "").strip()
    if not text:
        return
    sess.last_user_activity_ts = time.time()
    _cancel_auto_advance(sess)
    sess.last_user_input = text
    cond = sess.condition(sess.study_phase)
    if cond == "baseline":
        threading.Thread(target=_handle_baseline_input, args=(sess, text), daemon=True).start()
        return
    if not sess.openai_ws:
        return
    with sess.lock:
        sess.state["story_so_far"] += f"\nUser: {text}"
    try:
        sess.openai_ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": text}]},
        }))
        sess.openai_ws.send(json.dumps({"type": "response.create", "response": {"tool_choice": "required"}}))
    except Exception as e:
        print(f"[text_input error] {e}")


@app.route("/")
def index():
    return send_from_directory("public", "index.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory("public", path)


@app.route("/time_status")
def time_status():
    sess = _get_session(request.args.get("sid"))
    if not sess or sess.study_phase not in (3, 4):
        return jsonify({"active": False})
    cond = sess.condition(sess.study_phase)
    with sess.lock:
        bi = sess.state["beat_index"]
        beats = sess.state["beats"]
        tl = sess.state.get("time_limit", STORY_2_TIME_LIMIT)

    if cond == "time_constrained" and sess.monitor:
        si = min(bi, len(beats) - 1) if beats else 0
        t = sess.monitor.state(si, beats) if beats else {}
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
    sess = _get_session(request.args.get("sid"))
    if not sess:
        return jsonify({}), 404
    return jsonify(sess.snapshot())


@app.route("/save_questionnaire", methods=["POST"])
def save_questionnaire():
    try:
        data = request.get_json()
        sess = _get_session(data.get("sid"))
        if not sess:
            return jsonify({"saved": False, "error": "unknown session"}), 404

        phase = data.get("phase")
        responses = data.get("responses", {})

        phase_entry = sess.study_output.setdefault("phases", {}).setdefault(str(phase), {})
        phase_entry["questionnaire"] = responses
        phase_entry["questionnaire_saved_at"] = datetime.now().isoformat()
        _write_session_file(sess)

        print(f"[Study] Phase {phase} questionnaire saved → {sess.session_file_path}")
        return jsonify({"saved": True, "path": sess.session_file_path})
    except Exception as e:
        print(f"[save_questionnaire error] {e}")
        return jsonify({"saved": False, "error": str(e)})


if __name__ == "__main__":
    PORT = int(os.getenv("PORT", 3003))
    print(f"User Study server → http://localhost:{PORT}")
    socketio.run(app, host="0.0.0.0", port=PORT, debug=False, allow_unsafe_werkzeug=True)
