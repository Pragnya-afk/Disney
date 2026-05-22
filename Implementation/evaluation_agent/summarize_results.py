"""
evaluation_agent/summarize_results.py

Aggregate multi-run evaluation results and compute summary statistics.

This script:
1. Counts pairwise AB/BA winners per dimension across runs
2. Chooses a majority winner per dimension
3. Computes average single-story scores for baseline and director-agent

Example:
        python evaluation_agent/summarize_results.py \
            --scenario olaf_anna_courtyard \
            --runs 5
"""

import os
import sys
import json
import argparse
from statistics import mean

CURRENT_DIR = os.path.dirname(__file__)
IMPLEMENTATION_DIR = os.path.dirname(CURRENT_DIR)
sys.path.append(IMPLEMENTATION_DIR)


DIMENSIONS = [
    "Plot",
    "Development",
    "Language Use",
    "Interruption Handling",
    "Character Fidelity",
    "Narrative Control",
    "Overall",
]


def load_json(path: str):
    """
    Load a JSON file.
    """
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def init_win_counter():
    """
    Initialize win counters for each evaluation dimension.
    """
    return {
        dim: {
            "baseline": 0,
            "director_agent": 0,
            "same": 0,
        }
        for dim in DIMENSIONS
    }


def compute_majority_winner(counts: dict) -> str:
    """
    Compute the majority winner for one dimension.

    Rules:
    - If one method has strictly more wins than the others, return that method.
    - Otherwise return "same".

    Args:
        counts: Dictionary like
            {
                "baseline": 2,
                "director_agent": 3,
                "same": 0
            }

    Returns:
        "baseline", "director_agent", or "same"
    """

    baseline_count = counts["baseline"]
    director_count = counts["director_agent"]
    same_count = counts["same"]

    max_count = max(baseline_count, director_count, same_count)

    winners = []
    if baseline_count == max_count:
        winners.append("baseline")
    if director_count == max_count:
        winners.append("director_agent")
    if same_count == max_count:
        winners.append("same")

    # Unique majority
    if len(winners) == 1:
        return winners[0]

    # Tie
    return "same"


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--scenario",
        required=True,
        help="Scenario name, e.g. olaf_anna_courtyard",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=5,
        help="Number of evaluated runs.",
    )

    args = parser.parse_args()

    result_dir = os.path.join(
        IMPLEMENTATION_DIR,
        "evaluation_results",
        args.scenario,
    )

    win_counts = init_win_counter()

    baseline_scores = {dim: [] for dim in DIMENSIONS}
    director_scores = {dim: [] for dim in DIMENSIONS}

    # --------------------------------------------------------
    # Read all run-level evaluation results
    # --------------------------------------------------------

    for run_id in range(1, args.runs + 1):
        path = os.path.join(result_dir, f"pairwise_run_{run_id}.json")
        data = load_json(path)

        winners = data["aggregated_ab_ba_winners"]

        # Convert A/B labels to baseline/director_agent
        for dim in DIMENSIONS:
            winner = winners.get(dim, "Same")

            if winner == "A":
                win_counts[dim]["baseline"] += 1
            elif winner == "B":
                win_counts[dim]["director_agent"] += 1
            else:
                win_counts[dim]["same"] += 1

        # Collect single-story scores
        scores_a = data["single_story_scores"]["A"]["scores"]
        scores_b = data["single_story_scores"]["B"]["scores"]

        for dim in DIMENSIONS:
            a = scores_a.get(dim)
            b = scores_b.get(dim)

            if a is not None:
                baseline_scores[dim].append(a)
            if b is not None:
                director_scores[dim].append(b)

    # --------------------------------------------------------
    # Add majority winner per dimension
    # --------------------------------------------------------

    pairwise_summary = {}

    for dim in DIMENSIONS:
        counts = win_counts[dim]
        pairwise_summary[dim] = {
            "baseline": counts["baseline"],
            "director_agent": counts["director_agent"],
            "same": counts["same"],
            "majority_winner": compute_majority_winner(counts),
        }

    # --------------------------------------------------------
    # Average single-story scores
    # --------------------------------------------------------

    average_single_scores = {
        "baseline": {
            dim: (mean(baseline_scores[dim]) if baseline_scores[dim] else None)
            for dim in DIMENSIONS
        },
        "director_agent": {
            dim: (mean(director_scores[dim]) if director_scores[dim] else None)
            for dim in DIMENSIONS
        },
    }

    # --------------------------------------------------------
    # Final summary object
    # --------------------------------------------------------

    summary = {
        "scenario": args.scenario,
        "runs": args.runs,
        "pairwise_wins": pairwise_summary,
        "average_single_scores": average_single_scores,
    }

    output_path = os.path.join(result_dir, "summary.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"[summary] saved: {output_path}")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()