"""
run_noderail_baseline_and_eval.py

Runs the baseline (no director) on all 10 no-derailment scenarios from the
suite, then runs pairwise evaluation comparing each baseline run against the
corresponding director-agent run.

Baseline outputs  → outputs/baseline/{scenario_name}/batch/run_1.json
Director outputs  → outputs/director_agent/{scenario_name}/batch/run_1.json  (expected to exist)
Evaluation results→ evaluation_results/{scenario_name}/pairwise_run_1.json

Usage (run from Implementation/):
    python run_noderail_baseline_and_eval.py
    python run_noderail_baseline_and_eval.py --dry-run
    python run_noderail_baseline_and_eval.py --only baseline
    python run_noderail_baseline_and_eval.py --only eval
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CURRENT_DIR)
sys.path.insert(0, os.path.join(CURRENT_DIR, "director_agent"))
sys.path.insert(0, os.path.join(CURRENT_DIR, "evaluation_agent"))

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(os.path.join(CURRENT_DIR, ".env"))

from scenarios.olaf_derailment_scenario_suite import NO_DERAILMENT_SCENARIOS
from character_prompts.olaf import CHARACTER
from evaluation_agent.evaluation_core import (
    make_client,
    load_json,
    transcript_to_story,
    run_single_evaluation,
    run_ab_evaluation,
    convert_ba_to_original_labels,
    aggregate_ab_ba,
)

CHARACTER_MODULE = "character_prompts.olaf"
RUN_ID = 1
EVAL_MODEL = "gpt-4o"


# ── Baseline runner ────────────────────────────────────────────────────────────

def _call_llm(client: OpenAI, prompt: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
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


def _build_baseline_prompt(user_input, story_state, character, story_topic, beats):
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
    """Run the baseline (no director) on a scenario dict. Returns the saved path."""
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    scenario_name = scenario["scenario_name"]
    story_topic = scenario["story_topic"]
    beats = scenario["beats"]
    user_inputs = scenario["user_inputs"]

    output_dir = os.path.join(CURRENT_DIR, "outputs", "baseline", scenario_name, "batch")
    os.makedirs(output_dir, exist_ok=True)

    story_state = {
        "beat_index": 0,
        "completed_beats": [],
        "story_so_far": "",
    }
    transcript = []

    for turn_idx, user_input in enumerate(user_inputs, start=1):
        if story_state["beat_index"] >= len(beats):
            break

        current_beat = beats[story_state["beat_index"]]
        prompt = _build_baseline_prompt(user_input, story_state, character, story_topic, beats)
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


# ── Evaluation runner ──────────────────────────────────────────────────────────

def _build_character_profile(character: dict, scenario: dict) -> str:
    return json.dumps(
        {
            "character": character,
            "story_topic": scenario["story_topic"],
            "beats": scenario["beats"],
        },
        indent=2,
        ensure_ascii=False,
    )


def run_eval(scenario: dict, character: dict, run_id: int) -> str:
    """Run pairwise evaluation for one scenario. Returns the saved result path."""
    scenario_name = scenario["scenario_name"]

    baseline_path = os.path.join(
        CURRENT_DIR, "outputs", "baseline", scenario_name, "batch", f"run_{run_id}.json"
    )
    director_path = os.path.join(
        CURRENT_DIR, "outputs", "director_agent", scenario_name, "batch", f"run_{run_id}.json"
    )

    if not os.path.exists(baseline_path):
        print(f"  [eval] SKIP — baseline missing: {baseline_path}")
        return None
    if not os.path.exists(director_path):
        print(f"  [eval] SKIP — director output missing: {director_path}")
        return None

    character_profile = _build_character_profile(character, scenario)
    client = make_client()

    transcript_a = load_json(baseline_path)
    transcript_b = load_json(director_path)
    story_a = transcript_to_story(transcript_a)
    story_b = transcript_to_story(transcript_b)

    print(f"  [eval] scoring A (baseline)…")
    single_a = run_single_evaluation(client, EVAL_MODEL, story_a, character_profile)

    print(f"  [eval] scoring B (director)…")
    single_b = run_single_evaluation(client, EVAL_MODEL, story_b, character_profile)

    print(f"  [eval] pairwise AB…")
    ab_result = run_ab_evaluation(client, EVAL_MODEL, story_a, story_b, character_profile)

    print(f"  [eval] pairwise BA…")
    ba_result = run_ab_evaluation(client, EVAL_MODEL, story_b, story_a, character_profile)

    ba_converted = convert_ba_to_original_labels(ba_result["winners"])
    aggregated = aggregate_ab_ba(ab_result["winners"], ba_converted)

    result = {
        "timestamp": datetime.now().isoformat(),
        "run_id": run_id,
        "scenario": scenario_name,
        "character_module": CHARACTER_MODULE,
        "story_a_path": baseline_path,
        "story_b_path": director_path,
        "model": EVAL_MODEL,
        "single_story_scores": {"A_baseline": single_a, "B_director": single_b},
        "ab_evaluation": ab_result,
        "ba_evaluation": ba_result,
        "ba_winners_converted_to_original_labels": ba_converted,
        "aggregated_ab_ba_winners": aggregated,
    }

    result_dir = os.path.join(CURRENT_DIR, "evaluation_results", scenario_name)
    os.makedirs(result_dir, exist_ok=True)
    out_path = os.path.join(result_dir, f"pairwise_run_{run_id}.json")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"  [eval] saved → {out_path}")
    return out_path


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would run without executing.",
    )
    parser.add_argument(
        "--only",
        choices=["baseline", "eval"],
        default=None,
        help="Run only baseline or only eval.",
    )
    args = parser.parse_args()

    scenarios = NO_DERAILMENT_SCENARIOS
    print(f"No-derailment scenarios: {len(scenarios)}")
    print()

    # Determine what needs to run
    baseline_todo = []
    eval_todo = []

    for sc in scenarios:
        name = sc["scenario_name"]
        baseline_out = Path(CURRENT_DIR) / "outputs" / "baseline" / name / "batch" / f"run_{RUN_ID}.json"
        director_out = Path(CURRENT_DIR) / "outputs" / "director_agent" / name / "batch" / f"run_{RUN_ID}.json"
        eval_out = Path(CURRENT_DIR) / "evaluation_results" / name / f"pairwise_run_{RUN_ID}.json"

        if not args.only or args.only == "baseline":
            if baseline_out.exists():
                print(f"  [skip baseline] {name}")
            else:
                baseline_todo.append(sc)

        if not args.only or args.only == "eval":
            if eval_out.exists():
                print(f"  [skip eval]     {name}")
            elif not director_out.exists():
                print(f"  [skip eval — no director output] {name}")
            else:
                eval_todo.append(sc)

    print(f"\nTo run: {len(baseline_todo)} baseline + {len(eval_todo)} evaluations")

    if args.dry_run:
        print("\n-- dry run --")
        for sc in baseline_todo:
            print(f"  baseline: {sc['scenario_name']}")
        for sc in eval_todo:
            print(f"  eval:     {sc['scenario_name']}")
        return

    if not baseline_todo and not eval_todo:
        print("Nothing to run.")
        return

    completed, failed = 0, []

    # ── Baseline runs ──────────────────────────────────────────────────────────
    for i, sc in enumerate(baseline_todo, 1):
        name = sc["scenario_name"]
        print(f"\n[baseline {i}/{len(baseline_todo)}] {name}")
        try:
            run_baseline(sc, CHARACTER, RUN_ID)
            completed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed.append((f"baseline/{name}", str(e)))

    # ── Evaluation runs ────────────────────────────────────────────────────────
    for i, sc in enumerate(eval_todo, 1):
        name = sc["scenario_name"]
        print(f"\n[eval {i}/{len(eval_todo)}] {name}")
        try:
            run_eval(sc, CHARACTER, RUN_ID)
            completed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed.append((f"eval/{name}", str(e)))

    print(f"\n{'='*60}")
    print(f"Done. {completed}/{len(baseline_todo) + len(eval_todo)} succeeded, {len(failed)} failed.")
    if failed:
        print("\nFailed:")
        for label, err in failed:
            print(f"  {label}: {err}")


if __name__ == "__main__":
    main()
