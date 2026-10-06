"""
experiments/run_baseline_suite_rocket.py

Run the baseline (no director) for all 7 scenarios in the Rocket
red-riding-hood derailment suite. Mirrors run_baseline_suite.py
(which targets Olaf) but points at character_prompts.rocket /
scenarios.rocket_retells_red_riding_hood_scenario_suite.

Skips any scenario whose output file already exists.
Safe to interrupt and restart.

Usage (from Implementation/):
    python experiments/run_baseline_suite_rocket.py
    python experiments/run_baseline_suite_rocket.py --dry-run
"""

import argparse
import os
import sys
from pathlib import Path

IMPLEMENTATION_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, IMPLEMENTATION_DIR)

from run_baseline_suite import run_baseline, RUN_ID
from scenarios.rocket_retells_red_riding_hood_scenario_suite import SCENARIOS
from character_prompts.rocket import CHARACTER


def main():
    """Run the baseline for every Rocket suite scenario without an output yet."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true", help="Print what would run without executing."
    )
    args = parser.parse_args()

    scenario_list = sorted(SCENARIOS.keys())
    print(f"Suite: {len(scenario_list)} scenarios\n")

    todo = []
    for name in scenario_list:
        out = (
            Path(IMPLEMENTATION_DIR)
            / "outputs"
            / "baseline"
            / name
            / "batch"
            / f"run_{RUN_ID}.json"
        )
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
