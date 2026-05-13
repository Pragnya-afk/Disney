"""
baseline/runner.py

Run the non-interactive baseline multiple times.

Example:
    python baseline/runner.py \
      --character character_prompts.olaf \
      --scenario scenarios.olaf_anna_courtyard \
      --runs 5
"""

import argparse
from auto_main import run_story


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
        help="Scenario module, e.g. scenarios.olaf_anna_courtyard",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=5,
        help="Number of runs.",
    )

    args = parser.parse_args()

    for run_id in range(1, args.runs + 1):
        run_story(
            character_module=args.character,
            scenario_module=args.scenario,
            run_id=run_id,
        )


if __name__ == "__main__":
    main()