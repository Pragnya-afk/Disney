"""
director_agent/director_core.py

Director Agent module.
"""

import json
from openai import OpenAI

from director_prompt import DIRECTOR_SYSTEM_PROMPT, DIRECTOR_INSTRUCTIONS


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

    return f"""
{DIRECTOR_INSTRUCTIONS}

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