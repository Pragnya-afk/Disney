"""
evaluation/run_batch_eval.py

Run pairwise evaluation across multiple run pairs.

Example:
    python evaluation/run_batch_eval.py \
      --character character_prompts.olaf \
      --scenario olaf_anna_courtyard \
      --runs 5 \
      --model gpt-4o
"""

import os
import sys
import json
import argparse
import importlib
from datetime import datetime

CURRENT_DIR = os.path.dirname(__file__)
IMPLEMENTATION_DIR = os.path.dirname(CURRENT_DIR)
sys.path.append(IMPLEMENTATION_DIR)

from evaluation_agent import (
    make_client,
    load_json,
    transcript_to_story,
    run_single_evaluation,
    run_ab_evaluation,
    convert_ba_to_original_labels,
    aggregate_ab_ba,
)


def load_module(module_name: str):
    return importlib.import_module(module_name)


def build_character_profile(character_module: str, scenario_module: str) -> str:
    """
    Build a unified character profile string for evaluation.
    """

    char_mod = load_module(character_module)
    scen_mod = load_module(scenario_module)

    payload = {
        "character": char_mod.CHARACTER,
        "story_topic": scen_mod.SCENARIO["story_topic"],
        "beats": scen_mod.SCENARIO["beats"],
    }

    return json.dumps(payload, indent=2, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--character",
        required=True,
        help="Character module, e.g. character_prompts.olaf",
    )
    parser.add_argument(
        "--scenario",
        required=True,
        help="Scenario name only, e.g. olaf_anna_courtyard",
    )
    parser.add_argument(
        "--scenario-module",
        default=None,
        help="Optional full scenario module, e.g. scenarios.olaf_anna_courtyard",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=5,
        help="Number of run pairs.",
    )
    parser.add_argument(
        "--model",
        default="gpt-4o",
        help="Evaluator model.",
    )

    args = parser.parse_args()

    scenario_module = args.scenario_module or f"scenarios.{args.scenario}"
    character_profile = build_character_profile(args.character, scenario_module)

    client = make_client()

    result_dir = os.path.join(
        IMPLEMENTATION_DIR,
        "evaluation_results",
        args.scenario,
    )
    os.makedirs(result_dir, exist_ok=True)

    for run_id in range(1, args.runs + 1):
        story_a_path = os.path.join(
            IMPLEMENTATION_DIR,
            "outputs",
            "baseline",
            args.scenario,
            f"run_{run_id}.json",
        )
        story_b_path = os.path.join(
            IMPLEMENTATION_DIR,
            "outputs",
            "director_agent",
            args.scenario,
            f"run_{run_id}.json",
        )

        transcript_a = load_json(story_a_path)
        transcript_b = load_json(story_b_path)

        story_a = transcript_to_story(transcript_a)
        story_b = transcript_to_story(transcript_b)

        single_a = run_single_evaluation(
            client=client,
            model=args.model,
            story=story_a,
            character_profile=character_profile,
        )

        single_b = run_single_evaluation(
            client=client,
            model=args.model,
            story=story_b,
            character_profile=character_profile,
        )

        ab_result = run_ab_evaluation(
            client=client,
            model=args.model,
            story_a=story_a,
            story_b=story_b,
            character_profile=character_profile,
        )

        ba_result = run_ab_evaluation(
            client=client,
            model=args.model,
            story_a=story_b,
            story_b=story_a,
            character_profile=character_profile,
        )

        ba_converted = convert_ba_to_original_labels(ba_result["winners"])
        aggregated = aggregate_ab_ba(ab_result["winners"], ba_converted)

        result = {
            "timestamp": datetime.now().isoformat(),
            "run_id": run_id,
            "scenario": args.scenario,
            "character_module": args.character,
            "story_a_path": story_a_path,
            "story_b_path": story_b_path,
            "model": args.model,
            "single_story_scores": {
                "A": single_a,
                "B": single_b,
            },
            "ab_evaluation": ab_result,
            "ba_evaluation": ba_result,
            "ba_winners_converted_to_original_labels": ba_converted,
            "aggregated_ab_ba_winners": aggregated,
        }

        output_path = os.path.join(result_dir, f"pairwise_run_{run_id}.json")

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        print(f"[evaluation] saved: {output_path}")


if __name__ == "__main__":
    main()