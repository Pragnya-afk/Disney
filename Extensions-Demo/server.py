import os
import sys
import json
import base64
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from flask import Flask, send_from_directory, request, jsonify
from flask_socketio import SocketIO, emit
from dotenv import load_dotenv
from openai import OpenAI
import websocket

load_dotenv()

EXT_DIR = os.path.dirname(os.path.abspath(__file__))
IMPL_DIR = os.path.join(os.path.dirname(EXT_DIR), "Implementation")
sys.path.insert(0, IMPL_DIR)
sys.path.insert(0, os.path.join(IMPL_DIR, "director_agent"))
sys.path.insert(0, os.path.join(IMPL_DIR, "director_agent", "time_constrained"))
sys.path.insert(0, os.path.join(IMPL_DIR, "director_agent", "lenient"))
sys.path.insert(0, os.path.join(IMPL_DIR, "beat_generator"))
load_dotenv(os.path.join(IMPL_DIR, ".env"))

from director_core import (
    get_director_decision, last_character_opener, opener_guard_actor_text, strip_banned_opener,
)
from story_summary import build_director_story_context, needs_resummarize, update_summary
from lenient_director_core import get_lenient_director_decision
from consent import new_consent_state, apply_confirmation
from beat_compression import closing_instruction
from beat_generator import generate_story_spec, spec_to_scenario, validate_and_repair
from time_director_core import get_time_director_decision
from time_control import TemporalMonitor
from character_prompts.olaf import CHARACTER as OLAF_CHARACTER
from scenarios.olaf_derailment_scenario_suite import NO_DERAILMENT_SCENARIOS

VALID_MODES = {"director", "lenient", "time_constrained"}

PORT = int(os.getenv("PORT", 3004))
DIRECTOR_MODEL = "gpt-4o-mini"
SUMMARY_MODEL = "gpt-4o-mini"
BEAT_GEN_MODEL = "gpt-4o"
REALTIME_MODEL = "gpt-realtime"
TC_FINAL_BUFFER_SECONDS = 45.0
TC_MIN_MINUTES = 1.0
TC_MAX_MINUTES = 30.0

app = Flask(__name__, static_folder="public")
app.config["SECRET_KEY"] = "olaf-extensions-2026"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

api_key = os.getenv("OPENAI_API_KEY")
_client = OpenAI(api_key=api_key)

_SCENARIO_REGISTRY = {sc["scenario_name"]: sc for sc in NO_DERAILMENT_SCENARIOS}


def _make_label(key: str) -> str:
    label = key.replace("_no_derailment", "").replace("_", " ")
    return " ".join(w.capitalize() for w in label.split())


AVAILABLE_SCENARIOS = {k: _make_label(k) for k in _SCENARIO_REGISTRY}


#  Per-story / per-connection state
@dataclass
class StoryState:
    story_id: str
    scenario_key: str
    mode: str = "director"
    beats: list = field(default_factory=list)
    story_topic: str = ""
    title: str = ""
    beat_index: int = 0
    completed_beats: list = field(default_factory=list)
    story_so_far: str = ""
    story_summary: str = ""
    summarized_chars: int = 0
    turns_in_current_beat: int = 0
    expansion_index: int = 0
    turn_count: int = 0
    time_limit: float = 5.0
    consent: dict = field(default_factory=new_consent_state)
    continue_asks: int = 0
    closed: bool = False
    close_reason: "str | None" = None
    close_emitted: bool = False
    transcript: list = field(default_factory=list)
    monitor: "TemporalMonitor | None" = None
    paused_remaining_seconds: "float | None" = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "beat_index": self.beat_index,
                "completed_beats": list(self.completed_beats),
                "story_so_far": self.story_so_far,
                "story_summary": self.story_summary,
                "summarized_chars": self.summarized_chars,
                "turns_in_current_beat": self.turns_in_current_beat,
                "beats": self.beats,
                "story_topic": self.story_topic,
            }


@dataclass(eq=False)
class Session:
    sid: str
    stories: dict = field(default_factory=dict)      # story_id -> StoryState
    active_story_id: "str | None" = None
    generated: dict = field(default_factory=dict)     # story_id -> generated scenario spec
    openai_ws: "websocket.WebSocketApp | None" = None
    ws_story_id: "str | None" = None                  # which story the live realtime WS belongs to
    last_user_input: str = ""

    def active(self) -> "StoryState | None":
        if self.active_story_id is None:
            return None
        return self.stories.get(self.active_story_id)


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


def _close_ws(sess: Session):
    if sess.openai_ws:
        try:
            sess.openai_ws.close()
        except Exception:
            pass
        sess.openai_ws = None
    sess.ws_story_id = None


def _resolve_scenario(sess: Session, key: str) -> "dict | None":
    """Session-generated stories take priority over the fixed registry —
    sess.generated is per-session and never mutates the shared, thread-unsafe
    module-level _SCENARIO_REGISTRY.
    """
    if key in sess.generated:
        return sess.generated[key]
    return _SCENARIO_REGISTRY.get(key)


def _new_story(sess: Session, scenario_key: str, mode: str = "director", time_limit: float = 5.0) -> StoryState:
    if mode not in VALID_MODES:
        mode = "director"
    sc = _resolve_scenario(sess, scenario_key)
    if sc is None:
        raise KeyError(f"unknown scenario: {scenario_key}")
    story_id = f"story_{uuid.uuid4().hex[:8]}"
    st = StoryState(
        story_id=story_id,
        scenario_key=scenario_key,
        mode=mode,
        beats=sc["beats"],
        story_topic=sc["story_topic"],
        title=sc.get("title") or _make_label(scenario_key),
        time_limit=time_limit,
    )
    if mode == "time_constrained":
        st.monitor = TemporalMonitor(
            time_limit_minutes=time_limit, total_beats=len(st.beats),
            final_buffer_seconds=TC_FINAL_BUFFER_SECONDS,
        )
    sess.stories[story_id] = st
    sess.active_story_id = story_id
    return st


def _pause_active_monitor(sess: Session):
    """Freeze the currently-active story's countdown (if it's a
    time_constrained one) before its WS is closed for a switch/pause/new
    story — otherwise the clock silently keeps running via wall time while
    the story isn't even connected, which would burn its budget for no
    story progress at all.
    """
    st = sess.active()
    if st and st.mode == "time_constrained" and st.monitor is not None:
        st.paused_remaining_seconds = st.monitor.remaining_seconds()
        st.monitor = None


def _activate_story(sess: Session, st: StoryState):
    """Make st the session's active story, resuming its countdown (if
    time_constrained) from wherever it was frozen rather than from scratch.
    """
    if st.mode == "time_constrained" and st.monitor is None:
        remaining_minutes = (
            st.paused_remaining_seconds / 60 if st.paused_remaining_seconds is not None else st.time_limit
        )
        st.monitor = TemporalMonitor(
            time_limit_minutes=max(remaining_minutes, 0.05), total_beats=len(st.beats),
            final_buffer_seconds=TC_FINAL_BUFFER_SECONDS,
        )
        st.paused_remaining_seconds = None
    sess.active_story_id = st.story_id


def _reset_story(st: StoryState):
    """Re-init a StoryState in place for "start over" — keeps identity
    (story_id, scenario_key, mode, beats, story_topic, title) but wipes all
    progress. Callers must still close and reopen the realtime WS afterward:
    resetting this dict alone does not clear the actor's own conversation
    memory of the finished run.
    """
    with st.lock:
        st.beat_index = 0
        st.completed_beats = []
        st.story_so_far = ""
        st.story_summary = ""
        st.summarized_chars = 0
        st.turns_in_current_beat = 0
        st.expansion_index = 0
        st.turn_count = 0
        st.consent = new_consent_state()
        st.continue_asks = 0
        st.closed = False
        st.close_reason = None
        st.close_emitted = False
        st.transcript = []
        st.monitor = None
        st.paused_remaining_seconds = None
    if st.mode == "time_constrained":
        st.monitor = TemporalMonitor(
            time_limit_minutes=st.time_limit, total_beats=len(st.beats),
            final_buffer_seconds=TC_FINAL_BUFFER_SECONDS,
        )


#  Prompt building
def build_system_prompt(st: StoryState, current_instruction: str = "") -> str:
    beats = st.beats
    idx = st.beat_index
    safe_idx = min(idx, len(beats) - 1)
    current_beat = beats[safe_idx]
    next_beat = beats[safe_idx + 1]["name"] if safe_idx < len(beats) - 1 else "None"
    story_tail = st.story_so_far[-600:] if st.story_so_far else "(story just started)"
    instruction_block = f"""
## Director Instruction For This Turn (MANDATORY — follow exactly, including any [OPENER GUARD] line)
{current_instruction}
""" if current_instruction else ""

    return f"""
You are an interactive storytelling engine voicing {OLAF_CHARACTER['name']}.
You speak AS {OLAF_CHARACTER['name']}. Stay fully in character at all times.

CRITICAL: Before EVERY response you MUST call the get_director_decision tool.
Do not speak until you have received the director's instruction.
Use the returned director_instruction to guide exactly what you say.

{OLAF_CHARACTER["character_prompt"]}

## Story Topic
{st.story_topic}

## Actor Rules
- Speak only as {OLAF_CHARACTER['name']}. Never mention the Director or the tool.
- Keep responses short: 3–5 sentences, natural when read or spoken.
- The director_instruction in the tool result is mandatory — realize it.
- Vary tone: sometimes excited, sometimes curious, sometimes gentle.
- Do not start most turns with "Oh". Do not repeat the same phrases.
{instruction_block}
## Current Story State
Beat {idx + 1} of {len(beats)}: {current_beat["name"]}
Goal: {current_beat["goal"]}
Next beat: {next_beat}
Completed: {json.dumps(st.completed_beats)}

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


#  Lenient mode: consent-gated stop/jump/summarize/continue
def _get_lenient_decision(st: StoryState, snap: dict, director_story_state: dict, user_input: str, beats: list) -> dict:
    """Run the lenient director LLM call, then post-process its raw decision
    through consent.apply_confirmation — the state machine, not the LLM,
    decides whether a stop/jump/summarize/continue request actually fires.

    Returns a dict shaped like a normal director decision (director_instruction,
    decision_type, should_complete_beat) plus, only when an irreversible action
    is executing this turn, the private _lenient_close / _lenient_close_reason /
    _lenient_complete_all keys the caller uses to update StoryState.
    """
    with st.lock:
        consent_snapshot = dict(st.consent)
        continue_asks = st.continue_asks
        turn_count = st.turn_count

    consent_state = dict(consent_snapshot)
    consent_state["continue_asks"] = continue_asks

    try:
        raw_decision = get_lenient_director_decision(
            client=_client, model=DIRECTOR_MODEL,
            user_input=user_input, story_state=director_story_state,
            character=OLAF_CHARACTER, story_topic=snap["story_topic"],
            beats=beats, consent_state=consent_state,
        )
    except Exception as e:
        print(f"[lenient director error] {e}")
        raw_decision = {
            "director_instruction": "Continue the story naturally.",
            "decision_type": "progress_story",
            "confirmation_response": "none",
        }

    result = apply_confirmation(consent_snapshot, raw_decision, turn_count=turn_count)

    with st.lock:
        st.consent = result["consent"]
        if result["kind"] == "continue" and result["action"] == "ask":
            st.continue_asks += 1

    action = result["action"]

    if action == "ask":
        return {
            "director_instruction": result["prompt_text"],
            "decision_type": result["decision_type"],
            "should_complete_beat": False,
        }

    if action == "cancelled":
        return {
            "director_instruction": raw_decision.get("director_instruction")
                or "Warmly acknowledge and continue the story from where it stood.",
            "decision_type": result["decision_type"],
            "should_complete_beat": False,
        }

    if action == "execute":
        kind = result["kind"]
        if kind == "stop":
            return {
                "director_instruction": (
                    "The user confirmed they want to stop. Give a warm, brief 2-3 sentence "
                    "closing that wraps up the story where it stands right now and says goodbye."
                ),
                "decision_type": result["decision_type"],
                "should_complete_beat": False,
                "_lenient_close": True,
                "_lenient_close_reason": "stop_confirmed",
            }
        if kind == "jump":
            return {
                "director_instruction": closing_instruction(
                    beats, snap["beat_index"],
                    recap="The user asked to skip ahead to the ending — happily oblige.",
                ),
                "decision_type": result["decision_type"],
                "should_complete_beat": False,
                "_lenient_complete_all": True,
                "_lenient_close": True,
                "_lenient_close_reason": "jump_to_end",
            }
        if kind == "summarize":
            return {
                "director_instruction": closing_instruction(
                    beats, snap["beat_index"],
                    recap="The user asked for a summary of how the story ends — narrate it as a warm, condensed telling.",
                ),
                "decision_type": result["decision_type"],
                "should_complete_beat": False,
                "_lenient_complete_all": True,
                "_lenient_close": True,
                "_lenient_close_reason": "summarize_to_end",
            }
        # kind == "continue": the user affirmed they want to keep going — just
        # resume normal storytelling, nothing closes or skips.
        return {
            "director_instruction": raw_decision.get("director_instruction")
                or "Continue the story naturally, picking back up the thread.",
            "decision_type": result["decision_type"],
            "should_complete_beat": False,
        }

    # action == "none": nothing pending, and this turn didn't start a new
    # stop/jump/summarize request either — behave exactly like the normal
    # director's own decision.
    return raw_decision


#  Time-constrained mode: pace the story to fit a target duration
def _get_time_constrained_decision(st: StoryState, snap: dict, director_story_state: dict, user_input: str, beats: list) -> dict:
    """Mirrors User-Study/server.py's time_constrained turn handling (same
    pacing_mode → behavior mapping), adapted to per-story StoryState/locking
    and reusing beat_compression.closing_instruction for the "final" wrap-up
    instead of re-deriving the same beat-ranking text inline.

    Returns a normal-shaped decision (director_instruction, decision_type,
    should_complete_beat) plus private _tc_* bookkeeping keys the caller uses
    to advance beat_index correctly (final/critical can jump more than one
    beat at once) and to surface pacing/timing to the client UI.
    """
    si = min(snap["beat_index"], len(beats) - 1)
    current_beat = beats[si]

    temporal = st.monitor.state(si, beats) if st.monitor else {
        "elapsed_seconds": 0, "remaining_seconds": st.time_limit * 60, "pacing_mode": "normal",
    }
    pacing_mode = temporal.get("pacing_mode", "normal")

    try:
        decision = get_time_director_decision(
            client=_client, model=DIRECTOR_MODEL,
            user_input=user_input, story_state=director_story_state,
            character=OLAF_CHARACTER, story_topic=snap["story_topic"],
            beats=beats, temporal_state=temporal,
        )
    except Exception as e:
        print(f"[tc-director error] {e}")
        decision = {"director_instruction": "Continue the story naturally.", "decision_type": "progress_story"}

    suggested_exp = None
    target_idx = None  # explicit beat_index to jump to this turn, if pacing forces one

    if pacing_mode == "too_fast":
        decision["should_complete_beat"] = False
        exps = current_beat.get("expansions", [])
        ei = snap.get("expansion_index", 0)
        if ei < len(exps):
            suggested_exp = exps[ei]
            with st.lock:
                st.expansion_index = ei + 1
            decision["director_instruction"] = f"Ahead of schedule — expand using: {suggested_exp}"
        else:
            decision["director_instruction"] = "Ahead of schedule — enrich with emotional depth or sensory detail."
    elif pacing_mode == "final":
        decision["should_complete_beat"] = True
        decision["decision_type"] = "close_story"
        decision["director_instruction"] = closing_instruction(
            beats, si, recap="Time is almost up — close the story now."
        )
        target_idx = len(beats)
    elif pacing_mode == "hurry":
        if snap.get("turns_in_current_beat", 0) >= 2:
            decision["should_complete_beat"] = True
            decision["director_instruction"] = decision.get("director_instruction", "") + " Wrap up this beat now and move on."
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
            target_idx = next_high_idx

    decision["_tc_pacing_mode"] = pacing_mode
    decision["_tc_elapsed_seconds"] = temporal.get("elapsed_seconds", 0)
    decision["_tc_remaining_seconds"] = temporal.get("remaining_seconds", 0)
    decision["_tc_expansion_hint"] = suggested_exp
    decision["_tc_target_idx"] = target_idx
    print(f"[TC | {pacing_mode} | {temporal.get('remaining_seconds', 0):.0f}s left]")
    return decision


#  Director turn handling
def handle_director_tool(sess: Session, ws, event: dict):
    if sess.openai_ws is not ws:
        return   # stale callback from a websocket this session has since replaced

    st = sess.stories.get(sess.ws_story_id)
    if st is None:
        return

    args = json.loads(event.get("arguments", "{}"))
    user_input = args.get("user_input") or sess.last_user_input or "(no input)"

    with st.lock:
        st.turns_in_current_beat += 1
    snap = st.snapshot()

    beats = snap["beats"]
    # The director only ever needs a bounded view of the story so far — the
    # raw story_so_far in `snap` is left untouched (it still feeds the
    # actor's [-600:] tail and the transcript) and only this shallow-copied
    # dict gets the summarized/truncated version for the director call.
    director_story_state = dict(snap)
    director_story_state["story_so_far"] = build_director_story_context(snap)

    if st.closed:
        decision = {
            "director_instruction": (
                "The story has already ended. Warmly and briefly acknowledge that — "
                "do not continue the plot or introduce new events."
            ),
            "decision_type": "story_closed",
        }
    elif st.mode == "lenient":
        decision = _get_lenient_decision(st, snap, director_story_state, user_input, beats)
    elif st.mode == "time_constrained":
        decision = _get_time_constrained_decision(st, snap, director_story_state, user_input, beats)
    else:
        try:
            decision = get_director_decision(
                client=_client, model=DIRECTOR_MODEL,
                user_input=user_input, story_state=director_story_state,
                character=OLAF_CHARACTER, story_topic=snap["story_topic"],
                beats=beats,
            )
        except Exception as e:
            print(f"[director error] {e}")
            decision = {"director_instruction": "Continue the story naturally.", "decision_type": "progress_story"}

    safe_idx = min(snap["beat_index"], len(beats) - 1)
    current_beat = beats[safe_idx]
    next_beat = beats[safe_idx + 1]["name"] if safe_idx < len(beats) - 1 else "None"

    if decision.get("_lenient_complete_all"):
        with st.lock:
            for b in beats[st.beat_index:]:
                if b["name"] not in st.completed_beats:
                    st.completed_beats.append(b["name"])
            st.beat_index = len(beats)
            st.turns_in_current_beat = 0
            print(f"[Beats → all complete] {st.story_id}")
    elif decision.get("_tc_target_idx") is not None:
        with st.lock:
            idx = st.beat_index
            target = min(decision["_tc_target_idx"], len(beats))
            if idx < target:
                st.completed_beats.extend(b["name"] for b in beats[idx:target])
                st.beat_index = target
            st.turns_in_current_beat = 0
            st.expansion_index = 0
            print(f"[Beat → {st.beat_index} | tc:{decision.get('_tc_pacing_mode')}]")
    elif decision.get("should_complete_beat"):
        with st.lock:
            idx = st.beat_index
            if idx < len(beats):
                st.completed_beats.append(beats[idx]["name"])
                st.beat_index += 1
                st.turns_in_current_beat = 0
                print(f"[Beat → {st.beat_index}]")

    if decision.get("_lenient_close") or decision.get("decision_type") == "close_story":
        with st.lock:
            st.closed = True
            if decision.get("_lenient_close_reason"):
                st.close_reason = decision["_lenient_close_reason"]
            elif decision.get("_tc_pacing_mode") == "final":
                st.close_reason = "time_up"
            else:
                st.close_reason = "close_story"
        print(f"[Story closed] {st.story_id} reason={st.close_reason}")

    tool_result = {
        "director_instruction": decision.get("director_instruction", ""),
        "decision_type": decision.get("decision_type", "progress_story"),
        "current_beat": current_beat["name"], "current_beat_goal": current_beat["goal"],
        "next_beat": next_beat,
        "story_so_far_tail": snap["story_so_far"][-300:],
    }
    if st.mode == "time_constrained":
        tool_result["pacing_mode"] = decision.get("_tc_pacing_mode", "normal")
        tool_result["elapsed_seconds"] = decision.get("_tc_elapsed_seconds", 0)
        tool_result["remaining_seconds"] = decision.get("_tc_remaining_seconds", 0)
        if decision.get("_tc_expansion_hint"):
            tool_result["expansion_hint"] = decision["_tc_expansion_hint"]

    # Deterministically append the opener-diversity guard — the director LLM's
    # own free text has proven unreliable at restating this, so it's injected
    # here in plain code rather than left to the director's compliance.
    last_opener = last_character_opener(snap.get("story_so_far", ""))
    tool_result["director_instruction"] = (
        f"{tool_result['director_instruction']}\n\n[OPENER GUARD] {opener_guard_actor_text(last_opener)}"
    )

    ws.send(json.dumps({
        "type": "session.update",
        "session": {"type": "realtime", "instructions": build_system_prompt(st, tool_result["director_instruction"])},
    }))

    print(f"[Director: {decision.get('decision_type')}] {decision.get('director_instruction', '')[:60]}...")

    if sess.sid:
        emit_data = {
            "decision_type": decision.get("decision_type"),
            "instruction": decision.get("director_instruction", "")[:80],
            "beat_index": st.beat_index,
            "total_beats": len(beats),
        }
        if st.mode == "time_constrained":
            emit_data["pacing_mode"] = decision.get("_tc_pacing_mode", "normal")
            emit_data["elapsed_seconds"] = decision.get("_tc_elapsed_seconds", 0)
            emit_data["remaining_seconds"] = decision.get("_tc_remaining_seconds", 0)
        socketio.emit("director_decision", emit_data, room=sess.sid)

    st.transcript.append({
        "turn": len(st.transcript) + 1,
        "beat": current_beat["name"],
        "user_input": user_input,
        "director_decision": decision,
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


#  Realtime websocket lifecycle
def _maybe_resummarize(st: StoryState):
    """Fire-and-forget: fold older turns into st.story_summary if enough new
    content has built up. Runs off the turn's critical path — the director
    call above already has what it needs before this is even invoked.
    """
    with st.lock:
        snap = {
            "story_so_far": st.story_so_far,
            "story_summary": st.story_summary,
            "summarized_chars": st.summarized_chars,
        }
        story_topic = st.story_topic

    if not needs_resummarize(snap):
        return

    def _run():
        try:
            result = update_summary(_client, SUMMARY_MODEL, snap, story_topic)
            with st.lock:
                st.story_summary = result["story_summary"]
                st.summarized_chars = result["summarized_chars"]
            print(f"[Summary updated] story={st.story_id} summarized_chars={result['summarized_chars']}")
        except Exception as e:
            print(f"[summary error] {e}")

    threading.Thread(target=_run, daemon=True).start()


def run_openai_ws(sess: Session, story_id: str):
    st = sess.stories.get(story_id)
    if st is None:
        return

    def on_open(ws):
        ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "type": "realtime",
                "instructions": build_system_prompt(st),
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
        print(f"[OpenAI WS] connected for {story_id}, session configured")

    def on_message(ws, message):
        if sess.openai_ws is not ws:
            return   # this websocket has since been replaced/closed
        try:
            data = json.loads(message)
        except Exception:
            return

        etype = data.get("type", "")

        if etype == "session.created":
            if sess.sid:
                payload = {
                    "story_id": st.story_id,
                    "title": st.title,
                    "mode": st.mode,
                    "beats": list(st.beats),
                    "beat_index": st.beat_index,
                }
                if st.mode == "time_constrained":
                    payload["time_limit_seconds"] = st.time_limit * 60
                    payload["remaining_seconds"] = (
                        st.monitor.remaining_seconds() if st.monitor is not None
                        else (st.paused_remaining_seconds if st.paused_remaining_seconds is not None else st.time_limit * 60)
                    )
                socketio.emit("session_started", payload, room=sess.sid)

        elif etype == "response.output_audio.delta":
            if sess.sid:
                socketio.emit("audio_output", {"audio": data["delta"]}, room=sess.sid)

        elif etype == "response.output_audio_transcript.delta":
            delta = data.get("delta", "")
            if delta and sess.sid:
                socketio.emit("transcript_assistant", {"delta": delta}, room=sess.sid)

        elif etype == "conversation.item.input_audio_transcription.completed":
            transcript = data.get("transcript", "").strip()
            sess.last_user_input = transcript
            if transcript and sess.sid:
                socketio.emit("transcript_user", {"text": transcript}, room=sess.sid)

        elif etype == "response.function_call_arguments.done":
            if data.get("name") == "get_director_decision":
                threading.Thread(
                    target=handle_director_tool, args=(sess, ws, data), daemon=True
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
            if olaf_text:
                with st.lock:
                    last_opener = last_character_opener(st.story_so_far)
                    olaf_text = strip_banned_opener(olaf_text, last_opener)
                    st.story_so_far += f"\nOlaf: {olaf_text}\n"
                    st.turn_count += 1
                if st.transcript:
                    st.transcript[-1]["character_response"] = olaf_text
                _maybe_resummarize(st)

                # A closed story produces two response.done events like any
                # other turn (the tool-call one, then this real one) — only
                # this branch (olaf_text non-empty) is the one worth acting
                # on, and close_emitted makes the emit exactly-once even if
                # the user sends further messages after closing.
                ended_payload = None
                with st.lock:
                    if st.closed and not st.close_emitted:
                        st.close_emitted = True
                        ended_payload = {
                            "story_id": st.story_id,
                            "reason": st.close_reason,
                            "beats_completed": len(st.completed_beats),
                            "total_beats": len(st.beats),
                            "turns": len(st.transcript),
                        }
                if ended_payload and sess.sid:
                    socketio.emit("story_ended", ended_payload, room=sess.sid)
            if sess.sid:
                socketio.emit("response_done", {}, room=sess.sid)

        elif etype == "error":
            print(f"[OpenAI error] {data}")
            if sess.sid:
                socketio.emit("error", {"message": str(data.get("error", data))}, room=sess.sid)

    def on_error(ws, error):
        print(f"[OpenAI WS error] {error}")

    def on_close(ws, code, msg):
        print(f"[OpenAI WS closed] {code} {msg}")
        if sess.openai_ws is ws:
            sess.openai_ws = None
            sess.ws_story_id = None

    ws = websocket.WebSocketApp(
        f"wss://api.openai.com/v1/realtime?model={REALTIME_MODEL}",
        header={"Authorization": f"Bearer {api_key}"},
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    sess.openai_ws = ws
    sess.ws_story_id = story_id
    ws.run_forever()


#  Socket.IO handlers
@socketio.on("connect")
def on_connect():
    _create_session(request.sid)
    # The client's own socket.id does not reliably match request.sid on this
    # Flask-SocketIO/python-socketio version — tell the client its real
    # session key explicitly so /state and /save_session lookups resolve.
    emit("server_sid", {"sid": request.sid})
    print(f"[SocketIO] client connected: {request.sid}")


@socketio.on("disconnect")
def on_disconnect():
    sess = _remove_session(request.sid)
    if sess:
        _close_ws(sess)
    print(f"[SocketIO] client disconnected: {request.sid}")


@socketio.on("start_story")
def on_start_story(data):
    sess = _get_session(request.sid)
    if sess is None:
        sess = _create_session(request.sid)

    scenario_key = data.get("scenario")
    if _resolve_scenario(sess, scenario_key) is None:
        scenario_key = next(iter(_SCENARIO_REGISTRY))
    mode = data.get("mode", "director")
    try:
        time_limit = float(data.get("time_limit", 5.0))
    except (TypeError, ValueError):
        time_limit = 5.0
    time_limit = max(TC_MIN_MINUTES, min(TC_MAX_MINUTES, time_limit))

    _pause_active_monitor(sess)
    _close_ws(sess)
    st = _new_story(sess, scenario_key, mode=mode, time_limit=time_limit)

    t = threading.Thread(target=run_openai_ws, args=(sess, st.story_id), daemon=True)
    t.start()


@socketio.on("generate_beats")
def on_generate_beats(data):
    sess = _get_session(request.sid)
    if sess is None:
        sess = _create_session(request.sid)

    story_prompt = (data.get("prompt") or "").strip()
    if not story_prompt:
        emit("beats_error", {"message": "Please describe a story first."})
        return

    try:
        target_beats = int(data.get("target_beats", 6))
    except (TypeError, ValueError):
        target_beats = 6
    target_beats = max(4, min(8, target_beats))

    def _run():
        try:
            spec = generate_story_spec(
                client=_client, model=BEAT_GEN_MODEL,
                story_prompt=story_prompt, character=OLAF_CHARACTER,
                target_beats=target_beats,
            )
        except Exception as e:
            print(f"[beat generator error] {e}")
            socketio.emit("beats_error", {"message": "Couldn't generate a story from that — try rephrasing."}, room=sess.sid)
            return

        if not spec.get("beats"):
            socketio.emit("beats_error", {"message": "Couldn't come up with beats for that story — try being more specific."}, room=sess.sid)
            return

        gen_id = f"gen_{uuid.uuid4().hex[:8]}"
        sess.generated[gen_id] = spec_to_scenario(spec, gen_id)
        socketio.emit("beats_generated", {
            "story_id": gen_id,
            "story_topic": spec.get("story_topic", ""),
            "beats": spec.get("beats", []),
            "warnings": spec.get("_warnings", []),
        }, room=sess.sid)

    threading.Thread(target=_run, daemon=True).start()


@socketio.on("save_beats")
def on_save_beats(data):
    sess = _get_session(request.sid)
    if sess is None:
        return
    story_id = data.get("story_id")
    existing = sess.generated.get(story_id)
    if existing is None:
        emit("beats_error", {"message": "That generated story is no longer available — try generating again."})
        return

    spec, warnings = validate_and_repair({
        "base_name": existing.get("title", story_id),
        "story_topic": data.get("story_topic", existing.get("story_topic", "")),
        "beats": data.get("beats", []),
    })
    if not spec.get("beats"):
        emit("beats_error", {"message": "A story needs at least one beat."})
        return

    sess.generated[story_id] = spec_to_scenario(spec, story_id)
    emit("beats_saved", {"story_id": story_id, "beats": spec["beats"], "warnings": warnings})


@socketio.on("restart_story")
def on_restart_story(data):
    sess = _get_session(request.sid)
    if sess is None:
        return
    story_id = data.get("story_id")
    st = sess.stories.get(story_id)
    if st is None:
        return

    _pause_active_monitor(sess)
    _close_ws(sess)
    _reset_story(st)
    sess.active_story_id = st.story_id

    t = threading.Thread(target=run_openai_ws, args=(sess, st.story_id), daemon=True)
    t.start()


def _story_summary_dict(sess: Session, st: StoryState) -> dict:
    d = {
        "story_id": st.story_id,
        "title": st.title,
        "mode": st.mode,
        "beat_index": st.beat_index,
        "total_beats": len(st.beats),
        "closed": st.closed,
        "active": st.story_id == sess.active_story_id,
    }
    if st.mode == "time_constrained":
        if st.monitor is not None:
            d["remaining_seconds"] = round(st.monitor.remaining_seconds(), 1)
        elif st.paused_remaining_seconds is not None:
            d["remaining_seconds"] = round(st.paused_remaining_seconds, 1)
        else:
            d["remaining_seconds"] = st.time_limit * 60
    return d


@socketio.on("list_stories")
def on_list_stories():
    sess = _get_session(request.sid)
    if sess is None:
        emit("stories_list", [])
        return
    emit("stories_list", [_story_summary_dict(sess, st) for st in sess.stories.values()])


@socketio.on("switch_story")
def on_switch_story(data):
    sess = _get_session(request.sid)
    if sess is None:
        return
    story_id = data.get("story_id")
    st = sess.stories.get(story_id)
    if st is None:
        emit("error", {"message": "That story no longer exists."})
        return

    payload = {
        "story_id": st.story_id,
        "title": st.title,
        "mode": st.mode,
        "transcript": list(st.transcript),
        "beat_index": st.beat_index,
        "total_beats": len(st.beats),
        "closed": st.closed,
    }

    # Re-selecting the story that already owns the live WS is a no-op on the
    # connection — just resend its state so the client can resync its tabs.
    if story_id == sess.active_story_id and sess.openai_ws is not None:
        emit("story_switched", payload)
        return

    _pause_active_monitor(sess)
    _close_ws(sess)
    _activate_story(sess, st)
    t = threading.Thread(target=run_openai_ws, args=(sess, story_id), daemon=True)
    t.start()
    emit("story_switched", payload)


@socketio.on("pause_story")
def on_pause_story():
    sess = _get_session(request.sid)
    if sess is None:
        return
    _pause_active_monitor(sess)
    _close_ws(sess)


@socketio.on("audio_input")
def on_audio_input(data):
    sess = _get_session(request.sid)
    if sess and sess.openai_ws:
        try:
            sess.openai_ws.send(json.dumps({
                "type": "input_audio_buffer.append",
                "audio": data["audio"],
            }))
        except Exception as e:
            print(f"[audio_input error] {e}")


@socketio.on("text_input")
def on_text_input(data):
    sess = _get_session(request.sid)
    if sess is None or not sess.openai_ws:
        return
    text = data.get("text", "").strip()
    if not text:
        return
    st = sess.active()
    if st is None:
        return
    sess.last_user_input = text
    with st.lock:
        st.story_so_far += f"\nUser: {text}"
    try:
        sess.openai_ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message", "role": "user",
                "content": [{"type": "input_text", "text": text}],
            },
        }))
        sess.openai_ws.send(json.dumps({"type": "response.create"}))
    except Exception as e:
        print(f"[text_input error] {e}")


#  REST
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


@app.route("/state", methods=["GET"])
def get_state():
    sid = request.args.get("sid")
    sess = _get_session(sid)
    if sess is None:
        return jsonify({"error": "no session"}), 404
    st = sess.active()
    if st is None:
        return jsonify({"error": "no active story"}), 404
    return jsonify(st.snapshot())


@app.route("/save_session", methods=["POST"])
def save_session():
    sid = request.args.get("sid") or (request.get_json(silent=True) or {}).get("sid")
    sess = _get_session(sid)
    if sess is None:
        return jsonify({"saved": False, "error": "no session"})
    st = sess.active()
    if st is None:
        return jsonify({"saved": False, "error": "no active story"})

    try:
        output = {
            "scenario": st.scenario_key,
            "story_topic": st.story_topic,
            "beats_completed": st.beat_index,
            "completed_beats": list(st.completed_beats),
            "saved_at": datetime.now().isoformat(),
            "turns": list(st.transcript),
        }
        output_dir = os.path.join(EXT_DIR, "outputs")
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(output_dir, f"{timestamp}_{st.scenario_key}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        print(f"[Session saved] {path} ({len(st.transcript)} turns)")
        return jsonify({"saved": True, "path": path, "turns": len(st.transcript)})
    except Exception as e:
        print(f"Save error: {e}")
        return jsonify({"saved": False, "error": str(e)})


if __name__ == "__main__":
    print(f"Extensions Demo server running at http://localhost:{PORT}")
    socketio.run(app, host="0.0.0.0", port=PORT, debug=False, allow_unsafe_werkzeug=True)
