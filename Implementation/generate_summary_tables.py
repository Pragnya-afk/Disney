"""
generate_summary_tables.py

Convenience entry point for regenerating all evaluation summary tables.

Scans evaluation_results/ recursively for every pairwise evaluation JSON
(director vs baseline, CoDi vs director, and any future comparisons) and
produces up-to-date pivot tables in evaluation_summary/.

Adding a new evaluation and re-running this script is all that is needed
to update the tables — no manual editing required.

Outputs (evaluation_summary/):
    all_runs_flat.csv                      raw per-story records
    table_scores_by_metric.{csv,md,tex}    mean score per method per metric
    table_scores_by_scenario.{csv,md,tex}  mean Overall score per method per scenario
    table_derailment_robustness.{csv,md,tex} mean Overall by derailment level
    table_pairwise_wins.{csv,md,tex}       pairwise win counts per comparison pair

Usage (run from Implementation/):
    python generate_summary_tables.py
    python generate_summary_tables.py --input_dir evaluation_results --output_dir evaluation_summary
"""

import sys
import os
import subprocess

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Regenerate evaluation summary tables from all pairwise evaluation results. "
            "Re-run this script after adding any new evaluation JSON files to update the tables."
        )
    )
    parser.add_argument(
        "--input_dir",
        default="evaluation_results",
        help="Directory containing evaluation JSON files (searched recursively). Default: evaluation_results",
    )
    parser.add_argument(
        "--output_dir",
        default="evaluation_summary",
        help="Directory where summary tables will be written. Default: evaluation_summary",
    )
    args = parser.parse_args()

    summarize_script = os.path.join(CURRENT_DIR, "evaluation_agent", "summarize_evaluations.py")

    cmd = [
        sys.executable,
        summarize_script,
        "--input_dir", args.input_dir,
        "--output_dir", args.output_dir,
    ]

    print(f"Scanning: {args.input_dir}")
    print(f"Writing:  {args.output_dir}\n")

    result = subprocess.run(cmd, cwd=CURRENT_DIR)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
