"""
experiments/run_director_suite_rocket.py

Run the director agent (no time limit) for all 7 scenarios in the
Rocket red-riding-hood derailment suite. Mirrors the director phase
of run_full_suite.py (which targets Olaf) but points at
character_prompts.rocket / scenarios.rocket_retells_red_riding_hood_scenario_suite.

Skips any scenario whose output file already exists.
Safe to interrupt and restart.

Usage (from Implementation/):
    python experiments/run_director_suite_rocket.py
    python experiments/run_director_suite_rocket.py --dry-run
"""

import argparse
import os
import sys
from pathlib import Path

IMPLEMENTATION_DIR = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, IMPLEMENTATION_DIR)
sys.path.insert(0, os.path.join(IMPLEMENTATION_DIR, "director_agent"))

from scenarios.rocket_retells_red_riding_hood_scenario_suite import SCENARIOS
from director_agent.auto_main import run_story as run_director

CHARACTER = "character_prompts.rocket"
SCENARIO_MODULE = "scenarios.rocket_retells_red_riding_hood_scenario_suite"
RUN_ID = 1


def director_output_path(scenario_name: str) -> Path:
    return (
        Path(IMPLEMENTATION_DIR)
        / "outputs"
        / "director_agent"
        / scenario_name
        / "batch"
        / f"run_{RUN_ID}.json"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true", help="Print what would run without executing."
    )
    args = parser.parse_args()

    scenario_names = sorted(SCENARIOS.keys())
    print(f"Suite: {len(scenario_names)} scenarios\n")

    todo = []
    for name in scenario_names:
        out = director_output_path(name)
        if out.exists():
            print(f"  [skip] {name}")
        else:
            todo.append(name)

    print(f"\nTo run: {len(todo)} director scenarios")

    if args.dry_run:
        print("\n-- dry run, not executing --")
        for name in todo:
            print(f"  {name}")
        return

    if not todo:
        print("Nothing to run.")
        return

    completed, failed = 0, []
    for i, name in enumerate(todo, 1):
        print(f"\n[director {i}/{len(todo)}] {name}")
        try:
            path = run_director(
                character_module=CHARACTER,
                scenario_module=SCENARIO_MODULE,
                run_id=RUN_ID,
                scenario_name_override=name,
            )
            print(f"  saved: {path}")
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
