"""
evaluation_agent/run_codi_batch_eval.py

Batch pairwise evaluation of director_agent vs CoDi across all 30 olaf scenarios.
Uses the CODI evaluation context (11 dimensions):
  Base 8: Plot, Development, Language Use, Interruption Handling,
           Character Fidelity, Narrative Control, Anthropomorphism, Overall
  Extra 3: Detail & Thoroughness, Narrative Polish, Director Decision-Making

Outputs per scenario (in evaluation_results/codi_vs_director/<scenario>/):
  eval_run_1.json  — AB winners + single-story scores

Summary table written to evaluation_summary/codi_vs_director_summary.md

Usage (from Implementation/):
    python evaluation_agent/run_codi_batch_eval.py
    python evaluation_agent/run_codi_batch_eval.py --model gpt-4o --scenarios olaf_arendelle_tour_no_derailment
"""

import os
import sys
import json
import argparse
import importlib
from datetime import datetime

import pandas as pd

CURRENT_DIR = os.path.dirname(__file__)
IMPLEMENTATION_DIR = os.path.dirname(CURRENT_DIR)
sys.path.append(IMPLEMENTATION_DIR)

from evaluation_agent.evaluation_core import (
    make_client,
    load_json,
    run_codi_comparison,
    run_codi_quality_eval,
    convert_ba_to_original_labels,
    aggregate_ab_ba,
    CODI_DIMENSIONS,
)
from scenarios.olaf_derailment_scenario_suite import SCENARIOS


def build_character_profile(character_module: str, scenario_name: str) -> tuple:
    """Return (profile_json_str, character_name)."""
    char_mod = importlib.import_module(character_module)
    character = char_mod.CHARACTER
    scenario = SCENARIOS[scenario_name]

    profile = {
        "name": character["name"],
        "character_prompt": character["character_prompt"],
        "available_animations": character["available_animations"],
        "story_topic": scenario["story_topic"],
        "beats": scenario["beats"],
    }
    return json.dumps(profile, indent=2, ensure_ascii=False), character["name"]


def summarize_results(results_dir: str, summary_dir: str):
    """Read all codi_vs_director eval JSONs and produce summary tables."""
    score_rows = []
    win_rows = []

    result_path = os.path.join(results_dir, "codi_vs_director")
    for scenario_dir in sorted(os.listdir(result_path)):
        eval_file = os.path.join(result_path, scenario_dir, "eval_run_1.json")
        if not os.path.exists(eval_file):
            continue

        with open(eval_file) as f:
            data = json.load(f)

        scenario = data.get("scenario", scenario_dir)
        sss = data.get("single_story_scores", {})

        for label, key in [("director", "A_director"), ("codi", "B_codi")]:
            entry = sss.get(key, {})
            scores = entry.get("scores", {})
            if not scores:
                continue
            row = {"method": label, "scenario": scenario}
            for dim in CODI_DIMENSIONS:
                row[dim] = scores.get(dim)
            score_rows.append(row)

        winners = data.get("aggregated_ab_ba_winners", {})
        for metric, winner_label in winners.items():
            if metric not in CODI_DIMENSIONS:
                continue
            winner_method = (
                "director" if winner_label == "A"
                else "codi" if winner_label == "B"
                else "Same"
            )
            win_rows.append({
                "scenario": scenario,
                "metric": metric,
                "winner": winner_method,
            })

    if not score_rows:
        print("No results found to summarize.")
        return

    scores_df = pd.DataFrame(score_rows)
    for dim in CODI_DIMENSIONS:
        if dim in scores_df.columns:
            scores_df[dim] = pd.to_numeric(scores_df[dim], errors="coerce")

    # Table 1: mean score per method per metric
    present = [d for d in CODI_DIMENSIONS if d in scores_df.columns]
    scores_by_metric = scores_df.groupby("method")[present].mean().round(2)
    scores_by_metric = scores_by_metric.loc[
        [m for m in ["director", "codi"] if m in scores_by_metric.index]
    ]

    # Table 2: mean Overall per method per scenario
    scores_by_scenario = pd.pivot_table(
        scores_df, index="method", columns="scenario", values="Overall", aggfunc="mean"
    ).round(2)
    scores_by_scenario.columns.name = None
    scores_by_scenario = scores_by_scenario.loc[
        [m for m in ["director", "codi"] if m in scores_by_scenario.index]
    ]

    # Table 3: pairwise win counts per metric
    if win_rows:
        wins_df = pd.DataFrame(win_rows)
        win_counts = wins_df.pivot_table(
            index="metric", columns="winner", values="scenario", aggfunc="count", fill_value=0
        )
        win_counts.columns.name = None
        win_counts = win_counts.reindex(
            [d for d in CODI_DIMENSIONS if d in win_counts.index]
        )

    os.makedirs(summary_dir, exist_ok=True)

    scores_by_metric.to_csv(os.path.join(summary_dir, "codi_vs_director_scores_by_metric.csv"))
    scores_by_metric.to_markdown(os.path.join(summary_dir, "codi_vs_director_scores_by_metric.md"))

    scores_by_scenario.to_csv(os.path.join(summary_dir, "codi_vs_director_scores_by_scenario.csv"))
    scores_by_scenario.to_markdown(os.path.join(summary_dir, "codi_vs_director_scores_by_scenario.md"))

    if win_rows:
        win_counts.to_csv(os.path.join(summary_dir, "codi_vs_director_pairwise_wins.csv"))
        win_counts.to_markdown(os.path.join(summary_dir, "codi_vs_director_pairwise_wins.md"))

    print("\n=== Scores by Metric (mean across all scenarios) ===")
    print(scores_by_metric.to_markdown())
    print("\n=== Pairwise Win Counts by Metric ===")
    if win_rows:
        print(win_counts.to_markdown())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", default="character_prompts.olaf")
    parser.add_argument("--model", default="gpt-4o")
    parser.add_argument(
        "--out-dir",
        default=os.path.join(IMPLEMENTATION_DIR, "evaluation_results"),
    )
    parser.add_argument(
        "--summary-dir",
        default=os.path.join(IMPLEMENTATION_DIR, "evaluation_summary"),
    )
    parser.add_argument(
        "--scenarios",
        nargs="*",
        default=None,
        help="Subset of scenarios (default: all 30 olaf scenarios)",
    )
    parser.add_argument(
        "--skip-completed",
        action="store_true",
        default=True,
        help="Skip scenarios that already have an eval_run_1.json.",
    )
    args = parser.parse_args()

    all_scenarios = list(SCENARIOS.keys())
    scenarios = args.scenarios if args.scenarios else all_scenarios

    client = make_client()
    completed = 0
    skipped = 0

    for scenario_name in scenarios:
        if scenario_name not in SCENARIOS:
            print(f"[SKIP] Unknown scenario: {scenario_name}")
            continue

        out_dir = os.path.join(args.out_dir, "codi_vs_director", scenario_name)
        out_path = os.path.join(out_dir, "eval_run_1.json")

        if args.skip_completed and os.path.exists(out_path):
            print(f"[SKIP] Already done: {scenario_name}")
            skipped += 1
            continue

        codi_path = os.path.join(
            IMPLEMENTATION_DIR, "outputs", "codi", scenario_name, "batch", "run_1.json"
        )
        director_path = os.path.join(
            IMPLEMENTATION_DIR, "outputs", "director_agent", scenario_name, "batch", "run_1.json"
        )

        if not os.path.exists(codi_path):
            print(f"[SKIP] Missing CoDi output: {scenario_name}")
            continue
        if not os.path.exists(director_path):
            print(f"[SKIP] Missing director output: {scenario_name}")
            continue

        print(f"\n[EVAL] {scenario_name}")
        character_profile, character_name = build_character_profile(args.character, scenario_name)

        director_transcript = load_json(director_path)
        codi_transcript = load_json(codi_path)

        # AB: director=A, codi=B
        ab_result = run_codi_comparison(
            client=client,
            model=args.model,
            implementation_transcript=director_transcript,
            codi_transcript=codi_transcript,
            character_profile=character_profile,
            character_name=character_name,
            scenario_name=scenario_name,
        )

        # BA: swap order for position-bias mitigation, then convert back
        ba_result = run_codi_comparison(
            client=client,
            model=args.model,
            implementation_transcript=codi_transcript,
            codi_transcript=director_transcript,
            character_profile=character_profile,
            character_name=character_name,
            scenario_name=f"{scenario_name} (BA order)",
        )
        ba_converted = convert_ba_to_original_labels(ba_result["winners"])
        aggregated = aggregate_ab_ba(ab_result["winners"], ba_converted)

        # Single-story quality scoring (CODI 11 dims)
        director_quality = run_codi_quality_eval(
            client=client,
            model=args.model,
            transcript=director_transcript,
            system_name="Director Agent",
            character_profile=character_profile,
            character_name=character_name,
            scenario_name=scenario_name,
        )

        codi_quality = run_codi_quality_eval(
            client=client,
            model=args.model,
            transcript=codi_transcript,
            system_name="CoDi",
            character_profile=character_profile,
            character_name=character_name,
            scenario_name=scenario_name,
        )

        result = {
            "timestamp": datetime.now().isoformat(),
            "scenario": scenario_name,
            "character_module": args.character,
            "story_a_path": f"outputs/director_agent/{scenario_name}/batch/run_1.json",
            "story_b_path": f"outputs/codi/{scenario_name}/batch/run_1.json",
            "model": args.model,
            "single_story_scores": {
                "A_director": director_quality,
                "B_codi": codi_quality,
            },
            "ab_evaluation": ab_result,
            "ba_evaluation": ba_result,
            "ba_winners_converted_to_original_labels": ba_converted,
            "aggregated_ab_ba_winners": aggregated,
        }

        os.makedirs(out_dir, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        print(f"  saved: {out_path}")
        print(f"  aggregated AB/BA winners: {aggregated}")
        completed += 1

    print(f"\nDone. Completed {completed} scenario(s), skipped {skipped}.")

    print("\nGenerating summary tables...")
    summarize_results(args.out_dir, args.summary_dir)


if __name__ == "__main__":
    main()
