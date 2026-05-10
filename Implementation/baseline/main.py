"""
baseline/main.py

Simple baseline implementation.

There is only one LLM agent:
- It speaks as the character.
- It handles user input directly.
- It tries to progress the current story beat.
- It decides whether the beat is complete.

Run from the Implementation folder:

    python baseline/main.py
"""

import os
import sys
import json
from dotenv import load_dotenv
from openai import OpenAI


# ------------------------------------------------------------
# Import setup
# ------------------------------------------------------------

CURRENT_DIR = os.path.dirname(__file__)
IMPLEMENTATION_DIR = os.path.dirname(CURRENT_DIR)

# Allows imports from Implementation/character_prompts
sys.path.append(IMPLEMENTATION_DIR)


# ------------------------------------------------------------
# Choose character here
# ------------------------------------------------------------

from character_prompts.olaf import CHARACTER, STORY_TOPIC, BEATS

# To use Rocket instead, comment the Olaf import above and uncomment this:
# from character_prompts.rocket import CHARACTER, STORY_TOPIC, BEATS


# ------------------------------------------------------------
# Environment and OpenAI setup
# ------------------------------------------------------------

load_dotenv(os.path.join(IMPLEMENTATION_DIR, ".env"))

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

MODEL = "gpt-4o-mini"


# ------------------------------------------------------------
# System prompt
# ------------------------------------------------------------

BASELINE_SYSTEM_PROMPT = """
You are an interactive storytelling engine for an AI character.

You speak as the character.
You stay in character.
You continue the story beat-by-beat.
""".strip()


# ------------------------------------------------------------
# Prompt builder
# ------------------------------------------------------------

def build_baseline_prompt(
    user_input: str,
    story_state: dict,
) -> str:
    """
    Build the prompt for the baseline model.
    """

    current_beat = BEATS[story_state["beat_index"]]

    return f"""
You are controlling an interactive AI character.

The character must respond directly to the user, stay in character,
and continue the story beat-by-beat.

This is a BASELINE system:
- It may answer user input naturally.
- It should still try to progress the current beat.
- It does not need advanced interruption classification.
- Keep the response short and performable aloud.

Return valid JSON only.

## Character

Name:
{CHARACTER["name"]}

Character Prompt:
{CHARACTER["character_prompt"]}

Available animations:
{json.dumps(CHARACTER["available_animations"], indent=2)}

## Story Topic

{STORY_TOPIC}

## Narrative Arc

{json.dumps(BEATS, indent=2)}

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
  "character_response": "What {CHARACTER["name"]} says to the user.",
  "story_event": "One sentence describing what changed in the story.",
  "animation": "one animation from the available list",
  "beat_completed": false,
  "reason": "Briefly explain why the beat is or is not complete."
}}
""".strip()


# ------------------------------------------------------------
# LLM call
# ------------------------------------------------------------

def call_llm(prompt: str) -> str:
    """
    Send the baseline prompt to the LLM.
    """

    response = client.chat.completions.create(
        model=MODEL,
        temperature=0.7,
        messages=[
            {
                "role": "system",
                "content": BASELINE_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
    )

    return response.choices[0].message.content.strip()


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def safe_json_parse(raw: str) -> dict:
    """
    Safely parse the model output as JSON.

    If parsing fails, use a fallback response.
    """

    try:
        return json.loads(raw)

    except json.JSONDecodeError:
        return {
            "character_response": raw,
            "story_event": "The story continued.",
            "animation": CHARACTER["available_animations"][0],
            "beat_completed": False,
            "reason": "Model did not return valid JSON.",
            "raw_model_response": raw,
        }


def validate_animation(animation: str) -> str:
    """
    Ensure that the selected animation is valid.
    """

    if animation in CHARACTER["available_animations"]:
        return animation

    return CHARACTER["available_animations"][0]


# ------------------------------------------------------------
# Main loop
# ------------------------------------------------------------

def run():
    """
    Run the baseline interactive storytelling loop.
    """

    story_state = {
        "beat_index": 0,
        "completed_beats": [],
        "story_so_far": "",
    }

    output_dir = os.path.join(CURRENT_DIR, "outputs")
    os.makedirs(output_dir, exist_ok=True)

    transcript = []

    print("\nBaseline storytelling started.")
    print(f"Loaded character: {CHARACTER['name']}")
    print("Type your message. Type 'quit' to stop.\n")

    while story_state["beat_index"] < len(BEATS):
        current_beat = BEATS[story_state["beat_index"]]

        print(f"\nCurrent beat: {current_beat['name']}")
        user_input = input("You: ")

        if user_input.lower().strip() in ["quit", "exit", "stop"]:
            break

        prompt = build_baseline_prompt(
            user_input=user_input,
            story_state=story_state,
        )

        raw = call_llm(prompt)
        output = safe_json_parse(raw)

        output["animation"] = validate_animation(
            output.get("animation", CHARACTER["available_animations"][0])
        )

        print(f"\n{CHARACTER['name']}: {output['character_response']}")
        print(f"[Animation: {output['animation']}]")

        story_state["story_so_far"] += (
            f"\nUser: {user_input}"
            f"\n{CHARACTER['name']}: {output['character_response']}"
            f"\nEvent: {output['story_event']}\n"
        )

        transcript.append({
            "method": "baseline",
            "character": CHARACTER["name"],
            "beat": current_beat["name"],
            "user_input": user_input,
            "model_output": output,
        })

        if output.get("beat_completed") is True:
            story_state["completed_beats"].append(current_beat["name"])
            story_state["beat_index"] += 1

    transcript_path = os.path.join(
        output_dir,
        f"baseline_transcript_{CHARACTER['name'].lower()}.json",
    )

    with open(transcript_path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)

    print("\nStory finished or stopped.")
    print(f"Saved transcript to {transcript_path}")


if __name__ == "__main__":
    run()