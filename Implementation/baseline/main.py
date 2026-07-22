"""
baseline/main.py

Interactive baseline implementation.

Example:
    python baseline/main.py \
      --character character_prompts.olaf \
      --scenario scenarios.olaf_retells_red_riding_hood_derail
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


def build_prompt(user_input, character, beats, story_so_far=""):
    return f"""
You are an interactive AI character.

Respond to the user input while staying in character.

Keep responses short: 3-5 sentences, natural when read.

Return valid JSON only.

## Character
Name: {character["name"]}

Character Prompt:
{character["character_prompt"]}

Available animations:
{json.dumps(character["available_animations"], indent=2)}

## Narrative Arc
{json.dumps(beats, indent=2)}

## Story So Far
{story_so_far if story_so_far else "(story just started)"}

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


def run(character_module: str, scenario_module: str):
    character_mod = load_module(character_module)
    scenario_mod = load_module(scenario_module)

    character = character_mod.CHARACTER
    scenario = scenario_mod.SCENARIO

    beats = scenario["beats"]
    beat_index = 0

    scenario_folder = scenario_module.split('.')[-1]
    output_dir = os.path.join(
        IMPLEMENTATION_DIR,
        "outputs",
        "baseline",
        scenario_folder,
        "interactive",
    )
    os.makedirs(output_dir, exist_ok=True)
    transcript = []
    story_so_far = ""

    print("\nInteractive baseline started.")
    print(f"Loaded character: {character['name']}")
    print(f"Loaded scenario: {scenario['scenario_name']}")
    print("Type your message. Type 'quit' to stop.\n")

    while beat_index < len(beats):
        current_beat = beats[beat_index]
        print(f"\nCurrent beat: {current_beat['name']}")
        user_input = input("You: ")

        if user_input.lower().strip() in ["quit", "exit", "stop"]:
            break

        prompt = build_prompt(user_input, character, beats, story_so_far)
        raw = call_llm(prompt)
        output = safe_json_parse(raw, character["available_animations"][0])
        output["animation"] = validate_animation(output.get("animation", ""), character)

        print(f"\n{character['name']}: {output['character_response']}")
        print(f"[Animation: {output['animation']}]")

        story_so_far += f"\nUser: {user_input}\n{character['name']}: {output['character_response']}\n"

        transcript.append({
            "method": "baseline",
            "character": character["name"],
            "scenario": scenario["scenario_name"],
            "beat": current_beat["name"],
            "user_input": user_input,
            "model_output": output,
        })

        if output.get("beat_completed") is True:
            beat_index += 1

    transcript_path = os.path.join(output_dir, "interactive.json")

    with open(transcript_path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)

    print("\nStory finished or stopped.")
    print(f"Saved transcript to {transcript_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", required=True, help="e.g. character_prompts.olaf")
    parser.add_argument("--scenario", required=True, help="e.g. scenarios.olaf_anna_courtyard")
    args = parser.parse_args()

    run(args.character, args.scenario)


if __name__ == "__main__":
    main()