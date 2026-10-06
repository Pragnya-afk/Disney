import os
import re
import sys
import json
import threading
import uuid
from copy import deepcopy
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
    get_director_decision,
    last_character_opener,
    opener_guard_actor_text,
    strip_banned_opener,
    beat_pacing_label,
    pacing_instruction_suffix,
)
from story_summary import build_director_story_context, needs_resummarize, update_summary
from lenient_director_core import get_lenient_director_decision
from consent import new_consent_state, apply_confirmation
from beat_compression import closing_instruction, full_narration_instruction, skip_to_instruction
from beat_generator import generate_story_spec, spec_to_scenario, validate_and_repair
from time_director_core import get_time_director_decision
from time_control import TemporalMonitor
from character_prompts.olaf import CHARACTER as OLAF_CHARACTER
from character_prompts.rocket import CHARACTER as ROCKET_CHARACTER
from scenarios.olaf_derailment_scenario_suite import NO_DERAILMENT_SCENARIOS
from config import BEAT_GEN_MODEL, REALTIME_DIRECTOR_MODEL, REALTIME_MODEL, SUMMARY_MODEL

VALID_MODES = {"director", "lenient", "time_constrained"}
CHARACTER_REGISTRY = {"olaf": OLAF_CHARACTER, "rocket": ROCKET_CHARACTER}
DEFAULT_CHARACTER_KEY = "olaf"

PORT = int(os.getenv("PORT", 3004))
DIRECTOR_MODEL = REALTIME_DIRECTOR_MODEL
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
    # Fallback only — every built-in scenario carries its own "title" below.
    # Strips a leading/trailing "olaf" word so an untitled scenario still
    # doesn't display the narrator's name baked into the story's own title.
    label = key.replace("_no_derailment", "").replace("_", " ")
    words = [w for w in label.split() if w.lower() != "olaf"]
    return " ".join(w.capitalize() for w in words) or "Untitled Story"


AVAILABLE_SCENARIOS = {k: sc.get("title") or _make_label(k) for k, sc in _SCENARIO_REGISTRY.items()}

_OLAF_NAME_RE = re.compile(r"\bOlaf\b")


def _localize_scenario(sc: dict, character: dict) -> dict:
    """Rewrite a narrator-agnostic scenario's literal "Olaf" mentions to the
    selected character's name.

    Only scenarios flagged narrator_agnostic (third-person fairy-tale
    retellings with no Frozen-specific lore) get this treatment — the rest
    are Olaf's own personal/Frozen-universe memories and stay Olaf-only
    (enforced by the caller), so their text is never rewritten.
    """
    if character["name"] == "Olaf" or not sc.get("narrator_agnostic"):
        return sc
    name = character["name"]
    sc = deepcopy(sc)
    sc["story_topic"] = _OLAF_NAME_RE.sub(name, sc["story_topic"])
    for beat in sc.get("beats", []):
        beat["goal"] = _OLAF_NAME_RE.sub(name, beat["goal"])
        if beat.get("expansions"):
            beat["expansions"] = [_OLAF_NAME_RE.sub(name, e) for e in beat["expansions"]]
    return sc


#  Per-story / per-connection state
@dataclass
class StoryState:
    story_id: str
    scenario_key: str
    mode: str = "director"
    character_key: str = DEFAULT_CHARACTER_KEY
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
    tc_expand_cooldown: int = (
        0  # turns left in which too_fast must not re-expand after a hurry compression
    )
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
    stories: dict = field(default_factory=dict)  # story_id -> StoryState
    active_story_id: "str | None" = None
    generated: dict = field(default_factory=dict)  # story_id -> generated scenario spec
    openai_ws: "websocket.WebSocketApp | None" = None
    ws_story_id: "str | None" = None  # which story the live realtime WS belongs to
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


def _get_character(st: StoryState) -> dict:
    return CHARACTER_REGISTRY.get(st.character_key, OLAF_CHARACTER)


def _new_story(
    sess: Session,
    scenario_key: str,
    mode: str = "director",
    time_limit: float = 5.0,
    character_key: str = DEFAULT_CHARACTER_KEY,
) -> StoryState:
    if mode not in VALID_MODES:
        mode = "director"
    if character_key not in CHARACTER_REGISTRY:
        character_key = DEFAULT_CHARACTER_KEY
    sc = _resolve_scenario(sess, scenario_key)
    if sc is None:
        raise KeyError(f"unknown scenario: {scenario_key}")

    # Built-in scenarios that aren't flagged narrator_agnostic are Olaf's own
    # personal/Frozen-universe memories — force the narrator back to Olaf
    # rather than handing another character a story_topic that assumes lore
    # (being made by Elsa's magic, knowing Anna/Kristoff/Sven, etc.) they
    # don't have. User-generated stories (sess.generated) are exempt — those
    # are already built fresh for whichever character created them.
    is_builtin = scenario_key not in sess.generated and scenario_key in _SCENARIO_REGISTRY
    if is_builtin and not sc.get("narrator_agnostic"):
        character_key = DEFAULT_CHARACTER_KEY

    character = CHARACTER_REGISTRY[character_key]
    sc = _localize_scenario(sc, character)

    story_id = f"story_{uuid.uuid4().hex[:8]}"
    st = StoryState(
        story_id=story_id,
        scenario_key=scenario_key,
        mode=mode,
        character_key=character_key,
        beats=sc["beats"],
        story_topic=sc["story_topic"],
        title=sc.get("title") or _make_label(scenario_key),
        time_limit=time_limit,
    )
    if mode == "time_constrained":
        st.monitor = TemporalMonitor(
            time_limit_minutes=time_limit,
            total_beats=len(st.beats),
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
            st.paused_remaining_seconds / 60
            if st.paused_remaining_seconds is not None
            else st.time_limit
        )
        st.monitor = TemporalMonitor(
            time_limit_minutes=max(remaining_minutes, 0.05),
            total_beats=len(st.beats),
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
        st.tc_expand_cooldown = 0
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
            time_limit_minutes=st.time_limit,
            total_beats=len(st.beats),
            final_buffer_seconds=TC_FINAL_BUFFER_SECONDS,
        )


#  Prompt building
def build_system_prompt(st: StoryState, current_instruction: str = "") -> str:
    character = _get_character(st)
    beats = st.beats
    idx = st.beat_index
    safe_idx = min(idx, len(beats) - 1)
    current_beat = beats[safe_idx]
    next_beat = beats[safe_idx + 1]["name"] if safe_idx < len(beats) - 1 else "None"
    story_tail = st.story_so_far[-600:] if st.story_so_far else "(story just started)"
    instruction_block = (
        f"""
## Director Instruction For This Turn (MANDATORY — follow exactly, including any [OPENER GUARD] line)
{current_instruction}
"""
        if current_instruction
        else ""
    )

    return f"""
You are an interactive storytelling engine voicing {character['name']}.
You speak AS {character['name']}. Stay fully in character at all times.

CRITICAL: Before EVERY response you MUST call the get_director_decision tool.
Do not speak until you have received the director's instruction.
Use the returned director_instruction to guide exactly what you say.

{character["character_prompt"]}

## Story Topic
{st.story_topic}

## Actor Rules
- Speak only as {character['name']}. Never mention the Director or the tool.
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
        "properties": {"user_input": {"type": "string", "description": "What the user just said."}},
        "required": ["user_input"],
    },
}


#  Lenient mode: consent-gated stop/jump/summarize/continue
def _get_lenient_decision(
    st: StoryState,
    snap: dict,
    director_story_state: dict,
    user_input: str,
    beats: list,
    character: dict,
) -> dict:
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
            client=_client,
            model=DIRECTOR_MODEL,
            user_input=user_input,
            story_state=director_story_state,
            character=character,
            story_topic=snap["story_topic"],
            beats=beats,
            consent_state=consent_state,
        )
    except Exception as e:
        print(f"[lenient director error] {e}")
        raw_decision = {
            "director_instruction": "Continue the story naturally.",
            "decision_type": "progress_story",
            "confirmation_response": "none",
        }

    # "narrate_uninterrupted" is handled here, before consent.apply_confirmation,
    # rather than through the stop/jump/summarize state machine — the user asked
    # for the whole story at full detail, not to skip or end it early, so nothing
    # needs confirming. This still only fires when nothing else is pending: while
    # a stop/jump/summarize/continue confirmation is pending, the LLM is
    # instructed (see _consent_directive) to classify the reply against that
    # question instead of emitting a new decision_type.
    if raw_decision.get("decision_type") == "narrate_uninterrupted" and not consent_snapshot.get(
        "pending"
    ):
        return {
            "director_instruction": full_narration_instruction(
                beats,
                snap["beat_index"],
                recap="The user asked to hear the rest of the story told all the way through, without stopping — happily oblige.",
            ),
            "decision_type": "narrate_uninterrupted",
            "should_complete_beat": False,
            "_lenient_complete_all": True,
            "_lenient_close": True,
            "_lenient_close_reason": "narrate_uninterrupted",
        }

    result = apply_confirmation(consent_snapshot, raw_decision, turn_count=turn_count)

    with st.lock:
        st.consent = result["consent"]
        if result["kind"] == "continue" and result["action"] == "ask":
            st.continue_asks += 1

    action = result["action"]

    if action == "ask":
        prompt_text = result["prompt_text"]
        if result["kind"] == "jump" and result.get("target_beat"):
            matched = next((b for b in beats if b.get("name") == result["target_beat"]), None)
            if matched:
                prompt_text = f"Would you like to skip ahead to the \"{matched['name'].replace('_', ' ')}\" part?"
        return {
            "director_instruction": prompt_text,
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
            # Resolve target_beat (a beat "name" the LLM matched to the user's
            # description) to an index. Anything that doesn't resolve to a
            # genuine mid-story beat — no target_beat, unknown name, or a name
            # at/after the last beat — falls back to the original "jump to the
            # ending" behavior, same as before target_beat existed.
            target_name = result.get("target_beat")
            target_idx = None
            if target_name:
                for i, b in enumerate(beats):
                    if b.get("name") == target_name:
                        target_idx = i
                        break

            if target_idx is not None and snap["beat_index"] < target_idx < len(beats):
                target_label = beats[target_idx]["name"].replace("_", " ")
                return {
                    "director_instruction": skip_to_instruction(
                        beats,
                        snap["beat_index"],
                        target_idx,
                        recap=f"The user asked to skip ahead to the '{target_label}' part — happily oblige.",
                    ),
                    "decision_type": result["decision_type"],
                    "should_complete_beat": False,
                    "_lenient_target_idx": target_idx,
                }

            return {
                "director_instruction": closing_instruction(
                    beats,
                    snap["beat_index"],
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
                    beats,
                    snap["beat_index"],
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
def _get_time_constrained_decision(
    st: StoryState,
    snap: dict,
    director_story_state: dict,
    user_input: str,
    beats: list,
    character: dict,
) -> dict:
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

    temporal = (
        st.monitor.state(si, beats)
        if st.monitor
        else {
            "elapsed_seconds": 0,
            "remaining_seconds": st.time_limit * 60,
            "pacing_mode": "normal",
        }
    )
    pacing_mode = temporal.get("pacing_mode", "normal")

    # Right after hurry compressed LOW beats, beat progress jumps ahead of the
    # clock; without this the monitor would immediately flip to too_fast and
    # pad the story back out with expansions, oscillating between the two.
    with st.lock:
        cooldown = st.tc_expand_cooldown
        if cooldown:
            st.tc_expand_cooldown = cooldown - 1
    if cooldown and pacing_mode == "too_fast":
        pacing_mode = "normal"
        temporal = {**temporal, "pacing_mode": "normal"}

    try:
        decision = get_time_director_decision(
            client=_client,
            model=DIRECTOR_MODEL,
            user_input=user_input,
            story_state=director_story_state,
            character=character,
            story_topic=snap["story_topic"],
            beats=beats,
            temporal_state=temporal,
        )
    except Exception as e:
        print(f"[tc-director error] {e}")
        decision = {
            "director_instruction": "Continue the story naturally.",
            "decision_type": "progress_story",
        }

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
            decision["director_instruction"] = (
                "Ahead of schedule — enrich with emotional depth or sensory detail."
            )
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
            # Slightly behind: the LOW (flavour/transition) beats that follow are
            # compressed into a short transition rather than told in full, and the
            # story continues with the next MEDIUM or HIGH beat.
            k = si + 1
            while k < len(beats) and beats[k].get("importance") == "low":
                k += 1
            low_run = beats[si + 1 : k]
            if low_run and k < len(beats):
                compressed = "; ".join(
                    f"{b['name'].replace('_', ' ')} ({b['goal']})" for b in low_run
                )
                nxt = beats[k]
                decision["director_instruction"] = (
                    decision.get("director_instruction", "")
                    + f" Wrap up this beat now. Then compress the next part of the story — {compressed} — "
                    f"into one or two sentences, and continue with: {nxt['name']} — {nxt['goal']}"
                )
                target_idx = k
                with st.lock:
                    st.tc_expand_cooldown = 2
            else:
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
                decision.get("director_instruction", "")
                + f" Bridge immediately to: {next_high['name']} — {next_high['goal']}"
            )
            target_idx = next_high_idx

    decision["_tc_pacing_mode"] = pacing_mode
    decision["_tc_elapsed_seconds"] = temporal.get("elapsed_seconds", 0)
    decision["_tc_remaining_seconds"] = temporal.get("remaining_seconds", 0)
    decision["_tc_expansion_hint"] = suggested_exp
    decision["_tc_target_idx"] = target_idx
    print(f"[TC | {pacing_mode} | {temporal.get('remaining_seconds', 0):.0f}s left]")
    return decision


# Decisions that deliberately end, skip, summarize or pause the story (or ask
# the user to confirm doing so) -- beat-stall escalation must not push these
# back into "advance the current beat".
_NO_STALL_PRESSURE_TYPES = {
    "close_story",
    "story_closed",
    "stop_confirmed",
    "jump_to_end",
    "summarize_to_end",
    "narrate_uninterrupted",
}


def _with_pacing_pressure(instruction: str, st: "StoryState", snap: dict, decision: dict) -> str:
    """Append the beat-stall escalation text to the actor-facing instruction.

    Keyed on turns spent in the current beat (beat_pacing_label). Exempt
    decisions -- closing/skipping/confirmation turns, and time-constrained
    turns where the temporal monitor is deliberately holding (too_fast) or
    closing (final) the beat -- only get the repetition guard.
    """
    decision_type = decision.get("decision_type", "")
    exempt = (
        st.closed
        or decision_type in _NO_STALL_PRESSURE_TYPES
        or decision_type.startswith("request_")
        or any(key.startswith("_lenient_") for key in decision)
        or decision.get("_tc_pacing_mode") in ("too_fast", "final")
    )
    label = None if exempt else beat_pacing_label(snap.get("turns_in_current_beat", 0))
    return f"{instruction} {pacing_instruction_suffix(label)}".strip()


#  Director turn handling
def handle_director_tool(sess: Session, ws, event: dict):
    if sess.openai_ws is not ws:
        return  # stale callback from a websocket this session has since replaced

    st = sess.stories.get(sess.ws_story_id)
    if st is None:
        return

    character = _get_character(st)
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
    director_story_state["story_so_far"] = build_director_story_context(
        snap, character_name=character["name"]
    )

    if st.closed:
        decision = {
            "director_instruction": (
                "The story has already ended. Warmly and briefly acknowledge that — "
                "do not continue the plot or introduce new events."
            ),
            "decision_type": "story_closed",
        }
    elif st.mode == "lenient":
        decision = _get_lenient_decision(
            st, snap, director_story_state, user_input, beats, character
        )
    elif st.mode == "time_constrained":
        decision = _get_time_constrained_decision(
            st, snap, director_story_state, user_input, beats, character
        )
    else:
        try:
            decision = get_director_decision(
                client=_client,
                model=DIRECTOR_MODEL,
                user_input=user_input,
                story_state=director_story_state,
                character=character,
                story_topic=snap["story_topic"],
                beats=beats,
            )
        except Exception as e:
            print(f"[director error] {e}")
            decision = {
                "director_instruction": "Continue the story naturally.",
                "decision_type": "progress_story",
            }

    safe_idx = min(snap["beat_index"], len(beats) - 1)
    current_beat = beats[safe_idx]
    next_beat = beats[safe_idx + 1]["name"] if safe_idx < len(beats) - 1 else "None"

    if decision.get("_lenient_complete_all"):
        with st.lock:
            for b in beats[st.beat_index :]:
                if b["name"] not in st.completed_beats:
                    st.completed_beats.append(b["name"])
            st.beat_index = len(beats)
            st.turns_in_current_beat = 0
            print(f"[Beats → all complete] {st.story_id}")
    elif (
        decision.get("_tc_target_idx") is not None
        or decision.get("_lenient_target_idx") is not None
    ):
        with st.lock:
            idx = st.beat_index
            target_idx = decision.get("_tc_target_idx")
            if target_idx is None:
                target_idx = decision["_lenient_target_idx"]
            target = min(target_idx, len(beats))
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
        "current_beat": current_beat["name"],
        "current_beat_goal": current_beat["goal"],
        "next_beat": next_beat,
        "story_so_far_tail": snap["story_so_far"][-300:],
    }
    if st.mode == "time_constrained":
        tool_result["pacing_mode"] = decision.get("_tc_pacing_mode", "normal")
        tool_result["elapsed_seconds"] = decision.get("_tc_elapsed_seconds", 0)
        tool_result["remaining_seconds"] = decision.get("_tc_remaining_seconds", 0)
        if decision.get("_tc_expansion_hint"):
            tool_result["expansion_hint"] = decision["_tc_expansion_hint"]

    # Deterministically append the beat-stall escalation — the director prompt
    # only *asks* the model to escalate, so the pressure is enforced here.
    tool_result["director_instruction"] = _with_pacing_pressure(
        tool_result["director_instruction"], st, snap, decision
    )

    # Deterministically append the opener-diversity guard — the director LLM's
    # own free text has proven unreliable at restating this, so it's injected
    # here in plain code rather than left to the director's compliance.
    last_opener = last_character_opener(snap.get("story_so_far", ""), character["name"])
    tool_result["director_instruction"] = (
        f"{tool_result['director_instruction']}\n\n[OPENER GUARD] {opener_guard_actor_text(last_opener)}"
    )

    ws.send(
        json.dumps(
            {
                "type": "session.update",
                "session": {
                    "type": "realtime",
                    "instructions": build_system_prompt(st, tool_result["director_instruction"]),
                },
            }
        )
    )

    print(
        f"[Director: {decision.get('decision_type')}] {decision.get('director_instruction', '')[:60]}..."
    )

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

    st.transcript.append(
        {
            "turn": len(st.transcript) + 1,
            "beat": current_beat["name"],
            "user_input": user_input,
            "director_decision": decision,
            "character_response": "",
        }
    )

    ws.send(
        json.dumps(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": event["call_id"],
                    "output": json.dumps(tool_result),
                },
            }
        )
    )
    ws.send(json.dumps({"type": "response.create"}))


#  Realtime websocket lifecycle
def _maybe_resummarize(st: StoryState):
    """Fire-and-forget: fold older turns into st.story_summary if enough new
    content has built up. Runs off the turn's critical path — the director
    call above already has what it needs before this is even invoked.
    """
    character_name = _get_character(st)["name"]
    with st.lock:
        snap = {
            "story_so_far": st.story_so_far,
            "story_summary": st.story_summary,
            "summarized_chars": st.summarized_chars,
        }
        story_topic = st.story_topic

    if not needs_resummarize(snap, character_name=character_name):
        return

    def _run():
        try:
            result = update_summary(
                _client, SUMMARY_MODEL, snap, story_topic, character_name=character_name
            )
            with st.lock:
                st.story_summary = result["story_summary"]
                st.summarized_chars = result["summarized_chars"]
            print(
                f"[Summary updated] story={st.story_id} summarized_chars={result['summarized_chars']}"
            )
        except Exception as e:
            print(f"[summary error] {e}")

    threading.Thread(target=_run, daemon=True).start()


def run_openai_ws(sess: Session, story_id: str):
    st = sess.stories.get(story_id)
    if st is None:
        return

    def on_open(ws):
        character = _get_character(st)
        ws.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": {
                        "type": "realtime",
                        "instructions": build_system_prompt(st),
                        "audio": {
                            "output": {"voice": character.get("voice", "verse")},
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
                }
            )
        )
        print(f"[OpenAI WS] connected for {story_id}, session configured")

    def on_message(ws, message):
        if sess.openai_ws is not ws:
            return  # this websocket has since been replaced/closed
        try:
            data = json.loads(message)
        except Exception:
            return

        etype = data.get("type", "")

        if etype == "session.created":
            if sess.sid:
                character = _get_character(st)
                payload = {
                    "story_id": st.story_id,
                    "title": st.title,
                    "mode": st.mode,
                    "character": st.character_key,
                    "character_name": character["name"],
                    "audiofx": character.get("audiofx"),
                    "beats": list(st.beats),
                    "beat_index": st.beat_index,
                }
                if st.mode == "time_constrained":
                    payload["time_limit_seconds"] = st.time_limit * 60
                    payload["remaining_seconds"] = (
                        st.monitor.remaining_seconds()
                        if st.monitor is not None
                        else (
                            st.paused_remaining_seconds
                            if st.paused_remaining_seconds is not None
                            else st.time_limit * 60
                        )
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
            character_text = ""
            try:
                for item in data.get("response", {}).get("output", []):
                    for part in item.get("content", []):
                        txt = part.get("transcript") or part.get("text") or ""
                        character_text += txt
            except Exception:
                pass
            if character_text:
                character_name = _get_character(st)["name"]
                with st.lock:
                    last_opener = last_character_opener(st.story_so_far, character_name)
                    character_text = strip_banned_opener(character_text, last_opener)
                    st.story_so_far += f"\n{character_name}: {character_text}\n"
                    st.turn_count += 1
                if st.transcript:
                    st.transcript[-1]["character_response"] = character_text
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
    character_key = data.get("character", DEFAULT_CHARACTER_KEY)
    try:
        time_limit = float(data.get("time_limit", 5.0))
    except (TypeError, ValueError):
        time_limit = 5.0
    time_limit = max(TC_MIN_MINUTES, min(TC_MAX_MINUTES, time_limit))

    _pause_active_monitor(sess)
    _close_ws(sess)
    st = _new_story(
        sess, scenario_key, mode=mode, time_limit=time_limit, character_key=character_key
    )

    t = threading.Thread(target=run_openai_ws, args=(sess, st.story_id), daemon=True)
    t.start()


def _log_generated_beats(
    gen_id: str,
    spec: dict,
    source: str,
    story_prompt: "str | None" = None,
    target_beats: "int | None" = None,
) -> None:
    """Persist a generated (or user-edited) beat spec to disk for auditing.

    generate_story_spec()/save_beats otherwise only ever land in
    sess.generated — an in-memory dict, gone on server restart or as soon as
    a story moves past it. `source` is "generated" or "edited" so the two
    call sites (initial generation vs. a user's edit in the review screen)
    are distinguishable; `gen_id` ties both together across files.
    """
    try:
        output_dir = os.path.join(EXT_DIR, "outputs", "generated_beats")
        os.makedirs(output_dir, exist_ok=True)
        record = {
            "gen_id": gen_id,
            "source": source,
            "logged_at": datetime.now().isoformat(),
            "story_prompt": story_prompt,
            "target_beats": target_beats,
            "base_name": spec.get("base_name"),
            "story_topic": spec.get("story_topic"),
            "beats": spec.get("beats", []),
            "warnings": spec.get("_warnings", []),
        }
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(output_dir, f"{timestamp}_{gen_id}_{source}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
        print(f"[Beats logged] {path}")
    except Exception as e:
        print(f"[beat log error] {e}")


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
    character = CHARACTER_REGISTRY.get(data.get("character"), OLAF_CHARACTER)

    def _run():
        try:
            spec = generate_story_spec(
                client=_client,
                model=BEAT_GEN_MODEL,
                story_prompt=story_prompt,
                character=character,
                target_beats=target_beats,
            )
        except Exception as e:
            print(f"[beat generator error] {e}")
            socketio.emit(
                "beats_error",
                {"message": "Couldn't generate a story from that — try rephrasing."},
                room=sess.sid,
            )
            return

        if not spec.get("beats"):
            socketio.emit(
                "beats_error",
                {
                    "message": "Couldn't come up with beats for that story — try being more specific."
                },
                room=sess.sid,
            )
            return

        gen_id = f"gen_{uuid.uuid4().hex[:8]}"
        sess.generated[gen_id] = spec_to_scenario(spec, gen_id)
        _log_generated_beats(
            gen_id, spec, "generated", story_prompt=story_prompt, target_beats=target_beats
        )
        socketio.emit(
            "beats_generated",
            {
                "story_id": gen_id,
                "story_topic": spec.get("story_topic", ""),
                "beats": spec.get("beats", []),
                "warnings": spec.get("_warnings", []),
            },
            room=sess.sid,
        )

    threading.Thread(target=_run, daemon=True).start()


@socketio.on("save_beats")
def on_save_beats(data):
    sess = _get_session(request.sid)
    if sess is None:
        return
    story_id = data.get("story_id")
    existing = sess.generated.get(story_id)
    if existing is None:
        emit(
            "beats_error",
            {"message": "That generated story is no longer available — try generating again."},
        )
        return

    spec, warnings = validate_and_repair(
        {
            "base_name": existing.get("title", story_id),
            "story_topic": data.get("story_topic", existing.get("story_topic", "")),
            "beats": data.get("beats", []),
        }
    )
    if not spec.get("beats"):
        emit("beats_error", {"message": "A story needs at least one beat."})
        return

    sess.generated[story_id] = spec_to_scenario(spec, story_id)
    _log_generated_beats(story_id, spec, "edited")
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
        "character": st.character_key,
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

    character = _get_character(st)
    payload = {
        "story_id": st.story_id,
        "title": st.title,
        "mode": st.mode,
        "character": st.character_key,
        "character_name": character["name"],
        "audiofx": character.get("audiofx"),
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


@socketio.on("close_story_tab")
def on_close_story_tab(data):
    """Discard a story from the session entirely (its tab disappears).

    If it owns the live realtime WS, that connection is closed first so no
    late director/audio callbacks land on a story that no longer exists
    (handle_director_tool already no-ops once sess.stories has no entry).
    The client decides what to show next, based on `was_active` and the
    remaining stories in the accompanying stories_list.
    """
    sess = _get_session(request.sid)
    if sess is None:
        return
    story_id = data.get("story_id")
    if story_id not in sess.stories:
        emit("stories_list", [_story_summary_dict(sess, st) for st in sess.stories.values()])
        return

    was_active = story_id == sess.active_story_id
    if sess.ws_story_id == story_id:
        _close_ws(sess)
    del sess.stories[story_id]
    if was_active:
        sess.active_story_id = None

    print(f"[Story tab closed] {story_id} (was_active={was_active})")
    emit("story_tab_closed", {"story_id": story_id, "was_active": was_active})
    emit("stories_list", [_story_summary_dict(sess, st) for st in sess.stories.values()])


@socketio.on("audio_input")
def on_audio_input(data):
    sess = _get_session(request.sid)
    if sess and sess.openai_ws:
        try:
            sess.openai_ws.send(
                json.dumps(
                    {
                        "type": "input_audio_buffer.append",
                        "audio": data["audio"],
                    }
                )
            )
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
        sess.openai_ws.send(
            json.dumps(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": text}],
                    },
                }
            )
        )
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
    character_key = request.args.get("character", DEFAULT_CHARACTER_KEY)
    result = []
    for k, label in AVAILABLE_SCENARIOS.items():
        sc = _SCENARIO_REGISTRY.get(k, {})
        if character_key != DEFAULT_CHARACTER_KEY and not sc.get("narrator_agnostic"):
            continue  # Olaf's own personal/Frozen-universe stories stay Olaf-only
        result.append({"key": k, "label": label, "beat_count": len(sc.get("beats", []))})
    return jsonify(result)


@app.route("/characters", methods=["GET"])
def list_characters():
    return jsonify([{"key": k, "name": c["name"]} for k, c in CHARACTER_REGISTRY.items()])


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
            "character": st.character_key,
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
