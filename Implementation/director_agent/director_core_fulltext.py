"""
director_agent/director_core_fulltext.py

FULL-TEXT variant of the Director Agent module. Same call shape as
director_core.py, but the prompt is built around the complete prose
text of the story plus a "turns since last advancement" pacing signal,
instead of a beat list + beat_index. Reuses the opener-guard helpers
from director_core.py unchanged, since those don't depend on beats.
"""

import json
from openai import OpenAI

from director_core import last_character_opener, opener_guard_text
from director_prompt_fulltext import (
    DIRECTOR_SYSTEM_PROMPT_FULLTEXT,
    DIRECTOR_INSTRUCTIONS_FULLTEXT,
    PROGRESS_PACING_INSTRUCTIONS_FULLTEXT,
)


def progress_pacing_label(turns_since_progress: int) -> str:
    """Map turns spent without advancement to an escalating pacing label."""
    if turns_since_progress <= 1:
        return "on_track"
    if turns_since_progress == 2:
        return "lingering"
    if turns_since_progress <= 4:
        return "overdue"
    return "stalled"


def build_director_prompt_fulltext(
    user_input: str,
    story_state: dict,
    character: dict,
    full_story_text: str,
) -> str:
    """
    Build the full prompt for the full-text Director Agent.
    """

    turns_since_progress = story_state.get("turns_since_progress", 0)
    pacing_label = progress_pacing_label(turns_since_progress)

    last_opener = last_character_opener(story_state.get("story_so_far", ""))

    return f"""
{DIRECTOR_INSTRUCTIONS_FULLTEXT}

{PROGRESS_PACING_INSTRUCTIONS_FULLTEXT}

## Opener Guard — check this before writing director_instruction

{opener_guard_text(last_opener)}

## Character

Name:
{character["name"]}

Character Prompt:
{character["character_prompt"]}

## Full Story Text

{full_story_text}

## Turns Since Last Advancement

{turns_since_progress} turns — pacing label: {pacing_label}

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
  "should_advance_story": true,
  "reason": "Brief explanation of why this decision was chosen."
}}
""".strip()


def parse_director_json_fulltext(raw: str) -> dict:
    """
    Parse the full-text Director Agent response.
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
                "that advances the story."
            ),
            "should_advance_story": True,
            "reason": "Director response was not valid JSON.",
            "raw_model_response": raw,
        }


def get_director_decision_fulltext(
    client: OpenAI,
    model: str,
    user_input: str,
    story_state: dict,
    character: dict,
    full_story_text: str,
) -> dict:
    """
    Call the full-text Director Agent and return its structured decision.
    """

    prompt = build_director_prompt_fulltext(
        user_input=user_input,
        story_state=story_state,
        character=character,
        full_story_text=full_story_text,
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": DIRECTOR_SYSTEM_PROMPT_FULLTEXT,
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
    )

    raw = response.choices[0].message.content.strip()
    return parse_director_json_fulltext(raw)
