"""
baseline/auto_main.py

Non-interactive baseline story run.

Example:
    python baseline/auto_main.py \
      --character character_prompts.olaf \
      --scenario scenarios.olaf_retells_red_riding_hood_derail \
      --run-id 1
"""

import os
import sys
import json
import argparse
import importlib
from dotenv import load_dotenv
from openai import OpenAI

CURRENT_DIR = os.path.dirname(__file__)
IMPLEMENTATION_DIR = os.path.dirname(CURRENT_DIR)
sys.path.append(IMPLEMENTATION_DIR)

load_dotenv(os.path.join(IMPLEMENTATION_DIR, ".env"))

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = "gpt-4o-mini"


def load_module(module_name: str):
    return importlib.import_module(module_name)


def call_llm(prompt: str) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        temperature=0.7,
        messages=[
            {
                "role": "system",
                "content": "You are an interactive storytelling engine for an AI character.",
            },
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content.strip()


def build_prompt(user_input, story_state, character, story_topic, beats):
    current_beat = beats[story_state["beat_index"]]
    current_index = story_state["beat_index"]
    next_beat = beats[current_index + 1]["name"] if current_index < len(beats) - 1 else "None"

    return f"""
You are controlling an interactive AI character.

The character must respond directly to the user, stay in character,
and continue the story beat-by-beat.

This is a BASELINE system:
- It may answer user input naturally.
- It should still try to progress the current beat.
- It does not need advanced interruption classification.
- Keep the response short and performable aloud.
- The response should contain at least one concrete story event.

Return valid JSON only.

## Character
Name: {character["name"]}

Character Prompt:
{character["character_prompt"]}

Available animations:
{json.dumps(character["available_animations"], indent=2)}

## Story Topic
{story_topic}

## Narrative Arc
{json.dumps(beats, indent=2)}

## Current Beat
{current_beat["name"]}: {current_beat["goal"]}

## Next Beat
{next_beat}

## Completed Beats
{json.dumps(story_state["completed_beats"], indent=2)}

## Story So Far
{story_state["story_so_far"]}

## Latest User Input
{user_input}

## Output Format
{{
  "character_response": "What the character says to the user.",
  "story_event": "One sentence describing what changed in the story.",
  "animation": "one animation from the available list",
  "beat_completed": false,
  "reason": "Briefly explain why the beat is or is not complete."
}}
""".strip()


def safe_json_parse(raw, fallback_animation):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "character_response": raw,
            "story_event": "The story continued.",
            "animation": fallback_animation,
            "beat_completed": False,
            "reason": "Model did not return valid JSON.",
        }


def validate_animation(animation: str, character: dict) -> str:
    if animation in character["available_animations"]:
        return animation
    return character["available_animations"][0]


def run_story(character_module: str, scenario_module: str, run_id: int) -> str:
    character_mod = load_module(character_module)
    scenario_mod = load_module(scenario_module)

    character = character_mod.CHARACTER
    scenario = scenario_mod.SCENARIO

    story_topic = scenario["story_topic"]
    beats = scenario["beats"]
    user_inputs = scenario["user_inputs"]
    scenario_name = scenario["scenario_name"]

    # Use scenario module name for output folder
    scenario_folder = scenario_module.split('.')[-1]

    story_state = {
        "beat_index": 0,
        "completed_beats": [],
        "story_so_far": "",
    }

    output_dir = os.path.join(
        IMPLEMENTATION_DIR,
        "outputs",
        "baseline",
        scenario_folder,
        "batch",
    )
    os.makedirs(output_dir, exist_ok=True)

    transcript = []

    for turn_idx, user_input in enumerate(user_inputs, start=1):
        if story_state["beat_index"] >= len(beats):
            break

        current_beat = beats[story_state["beat_index"]]

        prompt = build_prompt(user_input, story_state, character, story_topic, beats)
        raw = call_llm(prompt)
        output = safe_json_parse(raw, character["available_animations"][0])
        output["animation"] = validate_animation(output.get("animation", ""), character)

        story_state["story_so_far"] += (
            f"\nUser: {user_input}"
            f"\n{character['name']}: {output['character_response']}"
            f"\nEvent: {output['story_event']}\n"
        )

        transcript.append({
            "method": "baseline",
            "character": character["name"],
            "scenario": scenario_name,
            "run_id": run_id,
            "turn_index": turn_idx,
            "beat": current_beat["name"],
            "user_input": user_input,
            "model_output": output,
        })

        if output.get("beat_completed") is True:
            story_state["completed_beats"].append(current_beat["name"])
            story_state["beat_index"] += 1

    transcript_path = os.path.join(output_dir, f"run_{run_id}.json")

    with open(transcript_path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)

    print(f"[baseline] saved: {transcript_path}")
    return transcript_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", required=True, help="e.g. character_prompts.olaf")
    parser.add_argument("--scenario", required=True, help="e.g. scenarios.olaf_retells_red_riding_hood_derail")
    parser.add_argument("--run-id", type=int, default=1)
    args = parser.parse_args()

    run_story(args.character, args.scenario, args.run_id)


if __name__ == "__main__":
    main()