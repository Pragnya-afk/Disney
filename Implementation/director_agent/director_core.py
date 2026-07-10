"""
director_agent/director_core.py

Director Agent module.
"""

import json
import re
from openai import OpenAI

from director_prompt import DIRECTOR_SYSTEM_PROMPT, DIRECTOR_INSTRUCTIONS, BEAT_PACING_INSTRUCTIONS

_OPENER_WORD_RE = re.compile(r"[A-Za-z']+")


def _normalize_opener(word: str) -> str:
    """Collapse repeated letters so 'Ooooh'/'Ohh'/'Oh' all normalize to the same form."""
    return re.sub(r"(.)\1+", r"\1", word.lower())


# Generic filler exclamations that are all interchangeable stalling tics —
# "Oh"/"Ooooh"/"Ohh" are the same tic wearing different spellings, so banning
# only the literal previous word let the model bounce between spellings.
# Stored pre-normalized so membership checks stay consistent with _normalize_opener.
_FILLER_OPENER_FAMILY = {
    _normalize_opener(w) for w in ("oh", "ooh", "well", "wow", "ah", "aw", "hmm", "hm")
}


def beat_pacing_label(turns_in_current_beat: int) -> str:
    """Map turns spent in the current beat to an escalating pacing label."""
    if turns_in_current_beat <= 1:
        return "on_track"
    if turns_in_current_beat == 2:
        return "lingering"
    if turns_in_current_beat <= 4:
        return "overdue"
    return "stalled"


def last_character_opener(story_so_far: str) -> str | None:
    """Return the first word of the character's most recent line in story_so_far, if any."""
    for line in reversed(story_so_far.strip().splitlines()):
        line = line.strip()
        if not line or line.lower().startswith("user:"):
            continue
        text = line.split(":", 1)[1].strip() if ":" in line else line
        match = _OPENER_WORD_RE.match(text)
        return match.group(0) if match else None
    return None


def opener_guard_text(last_opener: str | None) -> str:
    """Build the Opener Guard instruction text for a given previous opener word."""
    if not last_opener:
        return "None yet (this is the first turn). No opener restriction applies."

    if _normalize_opener(last_opener) in _FILLER_OPENER_FAMILY:
        return (
            f'The previous line opened with "{last_opener}" — a generic filler exclamation.\n\n'
            'BANNED for this turn: the entire filler-exclamation family, not just this exact '
            'spelling — "Oh", "Ooh", "Ohh", "Well", "Wow", "Ah", "Aw", "Hmm", and any close '
            'variant of these. Whatever opens this turn — the director_instruction, or the '
            'character line itself — must state the actual opening move explicitly: a concrete '
            'action, a name, a sound the character would genuinely make, direct address to the '
            'listener, or a line of dialogue. Do not leave the opening implicit and do not '
            'restate/paraphrase the last opener.'
        )
    return (
        f'The previous line opened with "{last_opener}".\n\n'
        f'BANNED for this turn: starting with "{last_opener}" again. Whatever opens this turn — '
        'the director_instruction, or the character line itself — must use a different, '
        'explicit opening move.'
    )


def opener_guard_actor_text(last_opener: str | None) -> str:
    """Terse opener-guard text for injection into the actor-facing director_instruction.

    Unlike opener_guard_text (used in the director LLM's own reasoning prompt),
    this is read by the realtime actor model as a literal instruction, not
    reasoned about — so it stays a single short imperative line while still
    preserving the filler-family ban that stops the model bouncing between
    filler spellings (e.g. "Oh" -> "Ooh" -> "Well").
    """
    if not last_opener:
        return "No opener restriction (first turn)."

    if _normalize_opener(last_opener) in _FILLER_OPENER_FAMILY:
        return (
            f'Do not open with "{last_opener}" or a similar filler (Ooh, Well, Wow, Ah, Hmm). '
            'Use a concrete action, name, sound, or line instead.'
        )
    return f'Do not open with "{last_opener}" again — use a different opening.'


def build_director_prompt(
    user_input: str,
    story_state: dict,
    character: dict,
    story_topic: str,
    beats: list,
) -> str:
    """
    Build the full prompt for the Director Agent.
    """

    current_index = story_state["beat_index"]
    current_beat = beats[current_index]

    previous_beat = beats[current_index - 1]["name"] if current_index > 0 else "None"
    next_beat = beats[current_index + 1]["name"] if current_index < len(beats) - 1 else "None"

    turns_in_current_beat = story_state.get("turns_in_current_beat", 0)
    pacing_label = beat_pacing_label(turns_in_current_beat)

    last_opener = last_character_opener(story_state.get("story_so_far", ""))

    return f"""
{DIRECTOR_INSTRUCTIONS}

{BEAT_PACING_INSTRUCTIONS}

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

{turns_in_current_beat} turns — pacing label: {pacing_label}

## Story So Far

{story_state["story_so_far"]}

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
  "reason": "Brief explanation of why this decision was chosen."
}}
""".strip()


def parse_director_json(raw: str) -> dict:
    """
    Parse the Director Agent response.
    """

    try:
        return json.loads(raw)
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
            "reason": "Director response was not valid JSON.",
            "raw_model_response": raw,
        }


def get_director_decision(
    client: OpenAI,
    model: str,
    user_input: str,
    story_state: dict,
    character: dict,
    story_topic: str,
    beats: list,
) -> dict:
    """
    Call the Director Agent and return its structured decision.
    """

    prompt = build_director_prompt(
        user_input=user_input,
        story_state=story_state,
        character=character,
        story_topic=story_topic,
        beats=beats,
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": DIRECTOR_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
    )

    raw = response.choices[0].message.content.strip()
    return parse_director_json(raw)