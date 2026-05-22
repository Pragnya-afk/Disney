"""
baseline/time_main.py

Interactive target-duration baseline implementation.

Example:
    python baseline/time_main.py \
      --character character_prompts.olaf \
      --scenario scenarios.olaf_retells_red_riding_hood_derail \
      --time-limit 5
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

from time_control import TemporalMonitor

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


def safe_json_parse(raw, fallback_animation):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "character_response": raw,
            "story_event": "The story continued.",
            "animation": fallback_animation,
            "beat_completed": False,
            "force_story_end": False,
            "reason": "Model did not return valid JSON.",
        }


def validate_animation(animation: str, character: dict) -> str:
    if animation in character["available_animations"]:
        return animation
    return character["available_animations"][0]


def build_prompt(user_input, story_state, character, story_topic, beats, temporal_state):
    current_beat = beats[story_state["beat_index"]]
    current_index = story_state["beat_index"]
    next_beat = beats[current_index + 1]["name"] if current_index < len(beats) - 1 else "None"

    return f"""
You are controlling an interactive AI character.

The character must respond directly to the user, stay in character,
and continue the story beat-by-beat.

This is a TARGET-DURATION BASELINE system.

The goal is not only to finish before the time limit.
The goal is to make the story last approximately the full target duration.

Use temporal_state to control pacing.

## Pacing Modes

1. too_fast
- The story is ahead of schedule.
- Do NOT complete the current beat unless absolutely necessary.
- Expand the current beat with meaningful detail, emotion, suspense, or character reaction.
- Do not add empty filler.
- Prefer beat_completed=false.

2. normal
- The story is on schedule.
- Continue the current beat naturally.

3. hurry
- The story is slightly behind schedule.
- Finish or nearly finish the current beat.
- Prefer beat_completed=true if the beat has mostly happened.

4. critical
- The story is far behind schedule.
- Compress the current and upcoming beats.
- Move clearly toward the ending.

5. final
- The story is almost out of time.
- Immediately give a clear and satisfying ending.
- Set force_story_end=true.

## General Rules

- Stay in character.
- Handle user interruptions briefly, then return to the story.
- Every response should contain at least one concrete story event.
- Keep the response short and performable aloud.
- Do not finish very early unless the final beat has truly been reached.

Return valid JSON only.

## Character

Name:
{character["name"]}

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

## Turns Spent In Current Beat

{story_state.get("turns_in_current_beat", 0)}

## Story So Far

{story_state["story_so_far"]}

## Temporal State

{json.dumps(temporal_state, indent=2)}

## Latest User Input

{user_input}

## Output Format

{{
  "character_response": "What the character says to the user.",
  "story_event": "One sentence describing what changed in the story.",
  "animation": "one animation from the available list",
  "beat_completed": false,
  "force_story_end": false,
  "reason": "Briefly explain why the beat is or is not complete."
}}
""".strip()


def should_complete_beat(output: dict, story_state: dict, temporal_state: dict) -> bool:
    pacing_mode = temporal_state.get("pacing_mode", "normal")
    turns_in_current_beat = story_state.get("turns_in_current_beat", 0)

    if pacing_mode == "too_fast" and turns_in_current_beat < 3:
        return False

    if output.get("beat_completed") is True:
        return True

    if pacing_mode in ["critical", "final"]:
        return True

    if pacing_mode == "hurry" and turns_in_current_beat >= 2:
        return True

    if turns_in_current_beat >= 3:
        return True

    return False


def should_close_story(output: dict, temporal_state: dict, monitor: TemporalMonitor, story_state: dict) -> bool:
    if temporal_state.get("pacing_mode") == "final":
        return True

    if output.get("force_story_end") is True:
        return monitor.should_allow_story_closure(story_state["beat_index"])

    return False


def run(character_module: str, scenario_module: str, time_limit: float):
    character_mod = load_module(character_module)
    scenario_mod = load_module(scenario_module)

    character = character_mod.CHARACTER
    scenario = scenario_mod.SCENARIO

    story_topic = scenario["story_topic"]
    beats = scenario["beats"]

    monitor = TemporalMonitor(
        time_limit_minutes=time_limit,
        total_beats=len(beats),
    )

    story_state = {
        "beat_index": 0,
        "completed_beats": [],
        "story_so_far": "",
        "turns_in_current_beat": 0,
    }

    output_dir = os.path.join(CURRENT_DIR, "outputs")
    os.makedirs(output_dir, exist_ok=True)
    transcript = []

    print("\nTarget-duration interactive baseline started.")
    print(f"Loaded character: {character['name']}")
    print(f"Loaded scenario: {scenario['scenario_name']}")
    print(f"Target duration: {time_limit} minutes")
    print("Type your message. Type 'quit' to stop.\n")

    while story_state["beat_index"] < len(beats):
        current_beat = beats[story_state["beat_index"]]
        temporal_state = monitor.state(story_state["beat_index"], beats)

        print(f"\nCurrent beat: {current_beat['name']}")
        print(f"Pacing mode: {temporal_state['pacing_mode']}")
        print(f"Elapsed time: {temporal_state['elapsed_seconds']} seconds")
        print(f"Remaining time: {temporal_state['remaining_seconds']} seconds")

        user_input = input("You: ")

        if user_input.lower().strip() in ["quit", "exit", "stop"]:
            break

        story_state["turns_in_current_beat"] += 1

        prompt = build_prompt(
            user_input=user_input,
            story_state=story_state,
            character=character,
            story_topic=story_topic,
            beats=beats,
            temporal_state=temporal_state,
        )

        raw = call_llm(prompt)
        output = safe_json_parse(raw, character["available_animations"][0])
        output["animation"] = validate_animation(output.get("animation", ""), character)

        print(f"\n{character['name']}: {output['character_response']}")
        print(f"[Animation: {output['animation']}]")

        story_state["story_so_far"] += (
            f"\nUser: {user_input}"
            f"\nTemporal Mode: {temporal_state['pacing_mode']}"
            f"\n{character['name']}: {output['character_response']}"
            f"\nEvent: {output['story_event']}\n"
        )

        transcript.append({
            "method": "target_duration_baseline",
            "character": character["name"],
            "scenario": scenario["scenario_name"],
            "time_limit_minutes": time_limit,
            "beat": current_beat["name"],
            "user_input": user_input,
            "temporal_state": temporal_state,
            "model_output": output,
        })

        if should_complete_beat(output, story_state, temporal_state):
            story_state["completed_beats"].append(current_beat["name"])
            story_state["beat_index"] += 1
            story_state["turns_in_current_beat"] = 0

        if should_close_story(output, temporal_state, monitor, story_state):
            break

        if monitor.should_stop_for_time():
            break

    transcript_path = os.path.join(
        output_dir,
        f"target_duration_baseline_transcript_{character['name'].lower()}_{scenario['scenario_name']}_{time_limit}min.json",
    )

    with open(transcript_path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)

    print("\nStory finished, stopped, or target duration reached.")
    print(f"Saved transcript to {transcript_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", required=True, help="e.g. character_prompts.olaf")
    parser.add_argument("--scenario", required=True, help="e.g. scenarios.olaf_retells_red_riding_hood_derail")
    parser.add_argument("--time-limit", type=float, default=5.0)
    args = parser.parse_args()

    run(args.character, args.scenario, args.time_limit)


if __name__ == "__main__":
    main()