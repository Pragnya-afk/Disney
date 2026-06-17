"""
run_baseline_suite.py

Run the baseline (no director) for ALL 30 scenarios in the suite.
Extends run_noderail_baseline_and_eval.py which only covers no-derailment.

Skips any scenario whose output file already exists.
Safe to interrupt and restart.

Usage (from Implementation/):
    python run_baseline_suite.py
    python run_baseline_suite.py --dry-run
"""

import argparse
import json
import os
import sys
from pathlib import Path

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CURRENT_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(CURRENT_DIR, ".env"))

from openai import OpenAI
from scenarios.olaf_derailment_scenario_suite import SCENARIOS
from character_prompts.olaf import CHARACTER

RUN_ID = 1
MODEL = "gpt-4o-mini"


def _call_llm(client, prompt):
    response = client.chat.completions.create(
        model=MODEL,
        temperature=0.7,
        messages=[
            {"role": "system", "content": "You are an interactive storytelling engine for an AI character."},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content.strip()


def _build_prompt(user_input, story_state, character, story_topic, beats):
    current_beat = beats[story_state["beat_index"]]
    idx = story_state["beat_index"]
    next_beat = beats[idx + 1]["name"] if idx < len(beats) - 1 else "None"

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


def _safe_parse(raw, fallback_animation):
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


def _validate_animation(animation, character):
    if animation in character["available_animations"]:
        return animation
    return character["available_animations"][0]


def run_baseline(scenario: dict, character: dict, run_id: int) -> str:
    """Run baseline on a scenario dict. Returns the saved transcript path."""
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    scenario_name = scenario["scenario_name"]
    story_topic = scenario["story_topic"]
    beats = scenario["beats"]
    user_inputs = scenario["user_inputs"]

    output_dir = os.path.join(CURRENT_DIR, "outputs", "baseline", scenario_name, "batch")
    os.makedirs(output_dir, exist_ok=True)

    story_state = {"beat_index": 0, "completed_beats": [], "story_so_far": ""}
    transcript = []

    for turn_idx, user_input in enumerate(user_inputs, start=1):
        if story_state["beat_index"] >= len(beats):
            break

        current_beat = beats[story_state["beat_index"]]
        prompt = _build_prompt(user_input, story_state, character, story_topic, beats)
        raw = _call_llm(client, prompt)
        output = _safe_parse(raw, character["available_animations"][0])
        output["animation"] = _validate_animation(output.get("animation", ""), character)

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

    out_path = os.path.join(output_dir, f"run_{run_id}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)

    print(f"  [baseline] saved → {out_path}")
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print what would run without executing.")
    args = parser.parse_args()

    scenario_list = sorted(SCENARIOS.keys())
    print(f"Suite: {len(scenario_list)} scenarios\n")

    todo = []
    for name in scenario_list:
        out = Path(CURRENT_DIR) / "outputs" / "baseline" / name / "batch" / f"run_{RUN_ID}.json"
        if out.exists():
            print(f"  [skip] {name}")
        else:
            todo.append(SCENARIOS[name])

    print(f"\nTo run: {len(todo)} baseline scenarios")

    if args.dry_run:
        print("\n-- dry run, not executing --")
        for sc in todo:
            print(f"  {sc['scenario_name']}")
        return

    if not todo:
        print("Nothing to run.")
        return

    completed, failed = 0, []
    for i, sc in enumerate(todo, 1):
        name = sc["scenario_name"]
        print(f"\n[{i}/{len(todo)}] {name}")
        try:
            run_baseline(sc, CHARACTER, RUN_ID)
            completed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed.append((name, str(e)))

    print(f"\n{'='*60}")
    print(f"Done. {completed}/{len(todo)} succeeded, {len(failed)} failed.")
    if failed:
        print("\nFailed runs:")
        for name, err in failed:
            print(f"  {name}: {err}")


if __name__ == "__main__":
    main()
