"""
director_agent/time_constrained/time_director_core.py

Target-duration Director Agent module.

This is based on director_core.py, but adds temporal_state so the director
can decide whether to slow down, continue normally, hurry, compress beats,
or close the story.
"""

import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))  # director_agent/

from openai import OpenAI

from director_prompt import DIRECTOR_SYSTEM_PROMPT, DIRECTOR_INSTRUCTIONS
from director_core import last_character_opener, opener_guard_text


TIME_DIRECTOR_INSTRUCTIONS = """
## Target-Duration Director Rules

You are operating under a target story duration.

The goal is not only to finish before the time limit.
The goal is to make the story last approximately the full target duration.

Use temporal_state to control pacing.

Pacing modes:

1. too_fast
- The story is ahead of schedule.
- MUST set should_complete_beat=false — the beat does not end this turn.
- If an expansion_hint is provided in the context, build the director_instruction around it.
- Otherwise expand with emotional depth, sensory detail, character reaction, or gentle user interaction.
- Do not invent new plot events — deepen what is already happening in the current beat.

2. normal
- The story is on schedule.
- Continue the current beat naturally.
- Progress the story, but do not rush.

3. hurry
- The story is slightly behind schedule.
- Make the actor finish or nearly finish the current beat.
- Set should_complete_beat=true.

4. critical
- The story is far behind schedule.
- MUST set should_complete_beat=true — the beat ends this turn regardless.
- The director_instruction must cover the current beat AND compress the next 1-2 beats into one response.
- Move clearly toward the ending.

5. final
- The story is almost out of time — the next response must be the last.
- MUST set should_complete_beat=true and decision_type="close_story".
- The director_instruction must resolve ALL remaining beats in one closing response.
- Keep the instruction short enough that the character can deliver it in under 30 seconds of speech.

Beat importance:
- Each beat has an importance level: high, medium, or low.
- HIGH beats are the story's essential moments — they must be narrated meaningfully, never skipped.
- MEDIUM beats are important but can be compressed to one or two sentences under time pressure.
- LOW beats are flavour/transition — they can be merged into an adjacent beat or omitted entirely when time is short.
- When critical or final, prioritise HIGH beats above all else.

Important:
- If pacing_mode is too_fast, stretch the story naturally.
- Do not create empty filler. Stretch by adding meaningful detail, suspense, emotion, or user-facing interaction.
- Do not close the story early unless temporal_state says final or the final beat is already reached.
- If the user interrupts, acknowledge briefly and use the interruption to enrich the current beat when the story is ahead of schedule.
""".strip()


def build_time_director_prompt(
    user_input: str,
    story_state: dict,
    character: dict,
    story_topic: str,
    beats: list,
    temporal_state: dict,
) -> str:
    current_index = story_state["beat_index"]
    current_beat = beats[current_index]

    previous_beat = beats[current_index - 1]["name"] if current_index > 0 else "None"
    next_beat = beats[current_index + 1]["name"] if current_index < len(beats) - 1 else "None"

    last_opener = last_character_opener(story_state.get("story_so_far", ""))

    return f"""
{DIRECTOR_INSTRUCTIONS}

{TIME_DIRECTOR_INSTRUCTIONS}

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

## Temporal State

{json.dumps(temporal_state, indent=2)}

## Latest User Input

{user_input}

## Output Format

Return valid JSON only in this exact structure:

{{
  "decision_type": "progress_story",
  "interruption_detected": false,
  "user_intent": "Briefly describe what the user is trying to do.",
  "director_instruction": "Concrete time-aware instruction for the actor. Do not write character dialogue.",
  "should_progress_current_beat": true,
  "should_complete_beat": false,
  "reason": "Brief explanation of why this decision was chosen."
}}
""".strip()


def parse_director_json(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "decision_type": "answer_and_steer_back",
            "interruption_detected": True,
            "user_intent": "Could not reliably parse the user's intent.",
            "director_instruction": (
                "Briefly acknowledge the user, then introduce one concrete new story event "
                "that advances the current beat. If the story is ahead of schedule, enrich the "
                "current beat with detail. If time is low, compress the remaining story and move "
                "toward the ending."
            ),
            "should_progress_current_beat": True,
            "should_complete_beat": False,
            "reason": "Director response was not valid JSON.",
            "raw_model_response": raw,
        }


def get_time_director_decision(
    client: OpenAI,
    model: str,
    user_input: str,
    story_state: dict,
    character: dict,
    story_topic: str,
    beats: list,
    temporal_state: dict,
) -> dict:
    prompt = build_time_director_prompt(
        user_input=user_input,
        story_state=story_state,
        character=character,
        story_topic=story_topic,
        beats=beats,
        temporal_state=temporal_state,
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