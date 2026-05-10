"""
director_agent/director_agent.py

Director Agent module.

This module implements the control component of the interactive
storytelling pipeline. Unlike the actor module, the Director Agent
does not produce in-character dialogue. Instead, it interprets the
latest user input in the context of the current story state and
returns a structured decision that guides the actor.

Core responsibilities
---------------------
- detect whether the user interrupted the flow of the story
- identify whether the latest user input is on-topic or off-topic
- decide how to steer the narrative back toward the intended arc
- determine whether the current beat should continue progressing
- determine whether the current beat has been completed

Design note
-----------
The actual prompt text used to control the Director Agent is stored
separately in `director_prompt.py`. This keeps prompt engineering
separate from control logic and makes the system easier to maintain,
analyze, and revise during experiments.

This file contains:
- prompt assembly logic
- JSON parsing for structured director outputs
- the LLM call used to obtain a director decision
"""

import json
from openai import OpenAI

# The prompt text is stored externally so that prompt design can be
# iterated independently of the program logic.
from director_prompt import DIRECTOR_SYSTEM_PROMPT, DIRECTOR_INSTRUCTIONS


# ------------------------------------------------------------
# Director prompt builder
# ------------------------------------------------------------

def build_director_prompt(
    user_input: str,
    story_state: dict,
    character: dict,
    story_topic: str,
    beats: list,
) -> str:
    """
    Build the full user prompt for the Director Agent.

    The Director Agent receives:
    1. general operating instructions from `DIRECTOR_INSTRUCTIONS`
    2. character information
    3. the story topic
    4. the full narrative arc
    5. the currently active beat
    6. already completed beats
    7. the story generated so far
    8. the latest user input
    9. the required JSON output schema

    Parameters
    ----------
    user_input : str
        The latest utterance or message provided by the user.

    story_state : dict
        Dictionary representing the current story state.
        Expected keys:
        - "beat_index": index of the currently active beat
        - "completed_beats": list of completed beat names or records
        - "story_so_far": textual summary or transcript of the story

    character : dict
        Character configuration dictionary.
        Expected keys:
        - "name"
        - "character_prompt"
        - "available_animations"

    story_topic : str
        High-level topic or premise of the story.

    beats : list
        Ordered list of narrative beats that define the intended arc.

    Returns
    -------
    str
        A fully assembled prompt string to be passed as the user
        message in the Director Agent LLM call.
    """

    # Select the currently active beat from the story arc.
    current_beat = beats[story_state["beat_index"]]

    # The prompt embeds the externally defined instructions from
    # director_prompt.py. This means the behavior of the Director Agent
    # can be adjusted by editing that file without modifying this code.
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

## Current Beat

{current_beat["name"]}: {current_beat["goal"]}

## Completed Beats

{json.dumps(story_state["completed_beats"], indent=2)}

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


# ------------------------------------------------------------
# Director JSON parser
# ------------------------------------------------------------

def parse_director_json(raw: str) -> dict:
    """
    Parse the Director Agent response as JSON.

    The Director Agent is instructed to return a structured JSON object.
    However, language models may still occasionally return invalid JSON,
    extra text, or malformed fields. This parser therefore includes a
    safe fallback so that the pipeline remains robust during runtime.

    Parameters
    ----------
    raw : str
        Raw text returned by the Director Agent.

    Returns
    -------
    dict
        Parsed Director decision dictionary. If parsing fails, a fallback
        decision is returned that safely acknowledges the issue and steers
        the story back toward the current beat.
    """

    try:
        return json.loads(raw)

    except json.JSONDecodeError:
        # Safe recovery strategy:
        # If the model output cannot be parsed, default to a conservative
        # decision that avoids crashing the program and encourages the
        # actor to briefly acknowledge the user before steering back.
        return {
            "decision_type": "answer_and_steer_back",
            "interruption_detected": True,
            "user_intent": "Could not reliably parse the user's intent.",
            "director_instruction": (
                "Briefly acknowledge the user, then guide the moment back "
                "to the current story beat."
            ),
            "should_progress_current_beat": False,
            "should_complete_beat": False,
            "reason": "Director response was not valid JSON.",
            "raw_model_response": raw,
        }


# ------------------------------------------------------------
# Director Agent call
# ------------------------------------------------------------

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
    Query the Director Agent and return a structured decision.

    This function performs three steps:
    1. Build the full prompt using the current story context
    2. Send the prompt to the selected LLM
    3. Parse the returned JSON into a Python dictionary

    Prompt usage
    ------------
    The Director Agent uses two prompt components imported from
    `director_prompt.py`:

    - DIRECTOR_SYSTEM_PROMPT:
      Used as the system message to define the high-level role and
      behavior of the Director Agent.

    - DIRECTOR_INSTRUCTIONS:
      Inserted into the user prompt to provide detailed task-specific
      instructions and output requirements.

    Parameters
    ----------
    client : OpenAI
        Initialized OpenAI client.

    model : str
        Model name, e.g. "gpt-4o-mini".

    user_input : str
        Latest user input.

    story_state : dict
        Current story state.

    character : dict
        Character configuration.

    story_topic : str
        High-level story topic.

    beats : list
        Ordered narrative beat list.

    Returns
    -------
    dict
        Structured director decision.
    """

    # Assemble the full prompt from current story context and the
    # reusable instructions defined in director_prompt.py.
    prompt = build_director_prompt(
        user_input=user_input,
        story_state=story_state,
        character=character,
        story_topic=story_topic,
        beats=beats,
    )

    # The system prompt sets the overall role of the model.
    # The user prompt contains the concrete current task instance.
    response = client.chat.completions.create(
        model=model,
        temperature=0.3,
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

    # Extract the returned text and attempt to parse it as JSON.
    raw = response.choices[0].message.content.strip()
    return parse_director_json(raw)