"""
director_agent/time_runner.py

Run the non-interactive target-duration director-agent version multiple times.

Example:
    python director_agent/time_runner.py \
      --character character_prompts.olaf \
      --scenario scenarios.olaf_retells_red_riding_hood_derail \
      --time-limit 5 \
      --runs 5
"""

import argparse
from time_auto_main import run_story


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
        help="Scenario module, e.g. scenarios.olaf_retells_red_riding_hood_derail",
    )

    parser.add_argument(
        "--time-limit",
        type=float,
        default=5.0,
        help="Target story duration in minutes.",
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
            time_limit=args.time_limit,
        )


if __name__ == "__main__":
    main()