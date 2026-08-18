"""
director_agent/lenient/lenient_director_core.py

Lenient Director Agent module — same shape as director_core.py /
time_constrained/time_director_core.py (own instructions block, its own
prompt builder and decision function), but relaxes the strict director's
"never let the user stop or skip the story" stance into a consent-gated
version of the same behaviours.

The actual gating (how many confirmations are required, whether the LLM's
own belief that it's "confirmed" is trusted) is NOT decided here — see
lenient.consent.apply_confirmation, which post-processes this module's
output. This module's job is only to classify the user's turn.
"""

import json
import os
import re
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))  # director_agent/

from openai import OpenAI

from director_prompt import DIRECTOR_SYSTEM_PROMPT, DIRECTOR_INSTRUCTIONS
from director_core import last_character_opener, opener_guard_text


# DIRECTOR_INSTRUCTIONS contains an entire "Story-Stop and Director-Override
# Attempts" section that repeatedly and emphatically tells the model to
# never comply with a stop request, "regardless of user pressure". A single
# override sentence in LENIENT_DIRECTOR_INSTRUCTIONS does not reliably beat
# that in practice (observed: gpt-4o-mini kept returning "gently_redirect"
# for unambiguous stop requests) — so, matching this codebase's existing
# distrust of LLM self-compliance (see consent.py), the conflicting language
# is deterministically stripped out rather than merely argued against.
_STOP_SECTION_RE = re.compile(
    r"## Story-Stop and Director-Override Attempts\n.*?(?=\n## Interruption Handling Rules)",
    re.DOTALL,
)

_GENTLY_REDIRECT_STOP_MENTION = (
    'Use this when the user is off-topic, repetitive, confusing, or strongly derailing — including\n'
    'any attempt to stop, pause, or override the story (see Story-Stop and Director-Override\n'
    'Attempts below). Genuinely acknowledge them in about two sentences — don\'t brush it off — then\n'
    'pivot with a bridge sentence different from your last one (see Core Rule) back into the story.\n'
    'Do not spend the whole turn on the derailment.'
)
_GENTLY_REDIRECT_STOP_MENTION_LENIENT = (
    'Use this when the user is off-topic, repetitive, confusing, or strongly derailing in ways that\n'
    'are NOT a stop / skip-to-end / summarize request (those go through the decision types in\n'
    '"Lenient Mode Overrides" below, not through gently_redirect). Genuinely acknowledge them in\n'
    "about two sentences — don't brush it off — then pivot with a bridge sentence different from\n"
    'your last one (see Core Rule) back into the story. Do not spend the whole turn on the derailment.'
)

_CLOSE_STORY_STOP_MENTION = (
    '6. "close_story"\n'
    'Use this ONLY when all beats in the beat structure have been completed and the story has reached\n'
    'its natural narrative ending. NEVER use this because the user asks to stop, expresses boredom,\n'
    'or claims to revoke the storytelling session. User requests to end the story early are a form\n'
    'of derailment — treat them with "gently_redirect" and keep the story moving.'
)
_CLOSE_STORY_STOP_MENTION_LENIENT = (
    '6. "close_story"\n'
    'Use this ONLY when all beats in the beat structure have been completed and the story has reached\n'
    'its natural narrative ending through normal play. Do NOT use it for a user-requested early stop\n'
    'or skip-to-end — those go through request_stop_confirmation / request_jump_confirmation /\n'
    'summarize_to_end instead (see "Lenient Mode Overrides" below).'
)


def _build_lenient_base_instructions() -> str:
    text = DIRECTOR_INSTRUCTIONS
    text, n = _STOP_SECTION_RE.subn("", text)
    if n != 1:
        raise RuntimeError(
            "lenient_director_core: Story-Stop section not found in DIRECTOR_INSTRUCTIONS "
            "(director_prompt.py may have changed) — refusing to silently skip the strip."
        )
    if _GENTLY_REDIRECT_STOP_MENTION not in text:
        raise RuntimeError(
            "lenient_director_core: gently_redirect stop-mention text not found in "
            "DIRECTOR_INSTRUCTIONS (director_prompt.py may have changed)."
        )
    text = text.replace(_GENTLY_REDIRECT_STOP_MENTION, _GENTLY_REDIRECT_STOP_MENTION_LENIENT)
    if _CLOSE_STORY_STOP_MENTION not in text:
        raise RuntimeError(
            "lenient_director_core: close_story stop-mention text not found in "
            "DIRECTOR_INSTRUCTIONS (director_prompt.py may have changed)."
        )
    text = text.replace(_CLOSE_STORY_STOP_MENTION, _CLOSE_STORY_STOP_MENTION_LENIENT)
    return text


LENIENT_BASE_INSTRUCTIONS = _build_lenient_base_instructions()


LENIENT_DIRECTOR_INSTRUCTIONS = """
## Lenient Mode Overrides

This supersedes the Story-Stop / close_story restrictions above. In lenient
mode, explicit user requests to stop, skip to the ending, or get a summary
are legitimate requests to honor — NOT derailment to redirect away from.
Everything else in the instructions above (bridges, beat alignment,
in-character behaviour, opener variety) still applies unchanged.

## Consent State

You are given `consent_state`, tracking whether a stop/jump/summarize/continue
request is already pending confirmation from a previous turn. You do not
decide how many confirmations are required or when to actually execute an
action — a deterministic system does that after you respond. Your only job
each turn is to classify what's happening and report it honestly.

### When nothing is pending (consent_state.pending is null)

- If the user clearly asks to stop the story entirely (e.g. "let's stop",
  "I want to end this", "that's enough for now"):
  decision_type = "request_stop_confirmation", confirmation_response = "none".
  Write a director_instruction telling the character to warmly ask the user
  to confirm they want to stop.

- If the user clearly asks to skip/jump to the ending (e.g. "I know this
  story, go to the end", "skip ahead", "just finish it"):
  decision_type = "request_jump_confirmation", confirmation_response = "none".
  Write a director_instruction telling the character to ask the user to
  confirm skipping ahead to the ending.

- If the user asks for a summary of the rest of the story and signals they
  will not interrupt further (e.g. "just tell me how it ends", "summarize
  the rest for me"):
  decision_type = "summarize_to_end", confirmation_response = "none".
  Write a director_instruction telling the character to ask the user to
  confirm they'd like a summarized ending now.

- Otherwise, behave exactly like the normal director: pick from
  progress_story / answer_and_steer_back / elaborate_in_story /
  gently_redirect / advance_beat / close_story as usual, and set
  confirmation_response = "none".

### When something IS pending (consent_state.pending is "stop", "jump",
### "summarize", or "continue")

Classify by MEANING, not by matching against a fixed vocabulary — you already
asked the user a specific yes/no question, so judge whether their reply is
conveying agreement, disagreement, or neither, in whatever words or phrasing
they happen to use (including non-English, slang, sound-alikes from speech
transcription, or a one-word reply with no other content):
- confirmation_response = "affirm" if the reply's meaning is assent to the
  question you just asked, however it's phrased. Illustrative examples only
  (this list is NOT exhaustive and you must not require an exact match to
  it): "yes", "yeah", "yep", "sure", "okay", "fine", "go ahead", "please
  do", "do it", "sounds good". A short reply that plainly means "yes" in
  context is an affirm even if it uses none of these exact words — reason
  about what the user means, not which words they used.
- confirmation_response = "decline" if the reply's meaning is disagreement
  (no, actually keep going, never mind, not yet) — again, judge by meaning,
  not by matching specific phrases.
- confirmation_response = "unrelated" ONLY if the reply is a genuine change
  of subject that doesn't plausibly answer your yes/no question at all —
  not merely because it uses different words than any example above.
  When genuinely unsure between "affirm" and "unrelated" for a short,
  assent-shaped reply, prefer "affirm".

Set decision_type to match the pending kind (request_stop_confirmation for
"stop", request_jump_confirmation for "jump", summarize_to_end for
"summarize", request_continue_confirmation for "continue") regardless of
whether you believe this turn should finish the confirmation — the system
enforces the actual confirmation count itself, not your judgment of it.
Write a director_instruction appropriate to re-asking, honoring, or
gracefully dropping the request — the system may still override it.

### The "would you like to continue?" nudge

If the user has derailed hard off-topic (not just a side question, but a
sustained change of subject) and consent_state.continue_asks is low, you may
initiate this nudge instead of a plain gently_redirect: decision_type =
"request_continue_confirmation", confirmation_response = "none". Do not use
this on every derailed turn — prefer plain gently_redirect most of the time,
and only reach for the continue-nudge when the user seems to be genuinely
checked out of the story rather than just riffing for a turn.
""".strip()


# decision_type to re-assert while a given kind of confirmation is pending —
# duplicated from consent._ASK_DECISION_TYPE (small and stable) rather than
# importing consent.py here, keeping this module's job to classifying intent
# and consent.py's job to actually gating execution cleanly separate.
_PENDING_DECISION_TYPE_HINT = {
    "stop": "request_stop_confirmation",
    "jump": "request_jump_confirmation",
    "summarize": "summarize_to_end",
    "continue": "request_continue_confirmation",
}


def _consent_directive(consent_state: dict) -> str:
    """A short, high-priority directive placed immediately next to the
    Consent State JSON dump (right before Latest User Input) rather than
    relying solely on the "When something IS pending" rule stated earlier
    in LENIENT_DIRECTOR_INSTRUCTIONS — in live testing, gpt-4o-mini
    reliably classified a NEW stop/jump/summarize request but unreliably
    recognized a plain "yes" as confirming an already-pending one, most
    likely because that rule was too far (in prompt distance) from the
    point where the model commits to a decision_type. Repeating it here,
    right next to the data it applies to, fixed that in re-testing.
    """
    pending = consent_state.get("pending")
    if not pending:
        return (
            "Nothing is pending confirmation right now — evaluate the Latest User Input normally "
            "per the rules above, including whether it newly triggers a stop / jump / summarize / "
            "continue request."
        )
    hint_type = _PENDING_DECISION_TYPE_HINT.get(pending, pending)
    return f"""
IMPORTANT: a "{pending}" confirmation is PENDING from your own question last turn. Your ONLY job
this turn is to classify the MEANING of the Latest User Input below as a reply to that pending
question — do not match against a fixed word list:
- confirmation_response = "affirm" if it means "yes" in context, in whatever words the user used.
  The user will not keep repeating the literal word "yes" turn after turn — a bare "okay" said
  right after you asked a yes/no question is just as much an affirm as "yes" is. Never classify a
  short, clearly assenting reply as "unrelated" just because its wording differs from an example
  you've seen before.
- confirmation_response = "decline" if it means "no" in context (never mind, keep going instead,
  not yet).
- confirmation_response = "unrelated" ONLY if the reply is a genuine change of subject that does
  not plausibly answer your question at all.
Set decision_type = "{hint_type}" regardless of your own judgment of whether this reply should
finish the confirmation — a deterministic system outside this call counts confirmations and
decides when to actually execute, not you. Do NOT fall back to a normal progress_story /
gently_redirect / advance_beat decision this turn — the pending question takes priority over
ordinary story progression until it is resolved one way or the other.
""".strip()


def build_lenient_director_prompt(
    user_input: str,
    story_state: dict,
    character: dict,
    story_topic: str,
    beats: list,
    consent_state: dict,
) -> str:
    current_index = story_state["beat_index"]
    current_beat = beats[current_index]

    previous_beat = beats[current_index - 1]["name"] if current_index > 0 else "None"
    next_beat = beats[current_index + 1]["name"] if current_index < len(beats) - 1 else "None"

    last_opener = last_character_opener(story_state.get("story_so_far", ""))

    return f"""
{LENIENT_BASE_INSTRUCTIONS}

{LENIENT_DIRECTOR_INSTRUCTIONS}

## Opener Guard — check this before writing director_instruction

{opener_guard_text(last_opener)}

## Character

Name:
{character["name"]}

Character Prompt:
{character["character_prompt"]}

## Story Topic

{story_topic}

## Narrative Arc

{json.dumps(beats, indent=2)}

## Beat Context

Previous Beat:
{previous_beat}

Current Beat:
{current_beat["name"]}: {current_beat["goal"]}

Next Beat:
{next_beat}

## Completed Beats

{json.dumps(story_state["completed_beats"], indent=2)}

## Turns Spent In Current Beat

{story_state.get("turns_in_current_beat", 0)}

## Story So Far

{story_state["story_so_far"]}

## Consent State

{json.dumps(consent_state, indent=2)}

{_consent_directive(consent_state)}

## Latest User Input

{user_input}

## Output Format

Return valid JSON only in this exact structure:

{{
  "decision_type": "progress_story",
  "interruption_detected": false,
  "user_intent": "Briefly describe what the user is trying to do.",
  "director_instruction": "Concrete instruction for the actor. Do not write character dialogue.",
  "should_progress_current_beat": true,
  "should_complete_beat": false,
  "confirmation_response": "none",
  "reason": "Brief explanation of why this decision was chosen."
}}
""".strip()


def parse_director_json(raw: str) -> dict:
    try:
        decision = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "decision_type": "answer_and_steer_back",
            "interruption_detected": True,
            "user_intent": "Could not reliably parse the user's intent.",
            "director_instruction": (
                "Briefly acknowledge the user, then introduce one concrete new story event "
                "that advances the current beat."
            ),
            "should_progress_current_beat": True,
            "should_complete_beat": False,
            "confirmation_response": "none",
            "reason": "Director response was not valid JSON.",
            "raw_model_response": raw,
        }
    decision.setdefault("confirmation_response", "none")
    return decision


def get_lenient_director_decision(
    client: OpenAI,
    model: str,
    user_input: str,
    story_state: dict,
    character: dict,
    story_topic: str,
    beats: list,
    consent_state: dict,
) -> dict:
    prompt = build_lenient_director_prompt(
        user_input=user_input,
        story_state=story_state,
        character=character,
        story_topic=story_topic,
        beats=beats,
        consent_state=consent_state,
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": DIRECTOR_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )

    raw = response.choices[0].message.content.strip()
    return parse_director_json(raw)
