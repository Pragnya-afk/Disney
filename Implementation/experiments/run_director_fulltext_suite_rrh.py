"""
experiments/run_director_fulltext_suite_rrh.py

Run the FULL-TEXT director (director_agent_fulltext) for all 7
scenarios in the Olaf red-riding-hood derailment suite, for direct
comparison against the existing beats-based director runs already in
outputs/director_agent/olaf_retells_red_riding_hood_*.

Skips any scenario whose output file already exists.
Safe to interrupt and restart.

Usage (from Implementation/):
    python experiments/run_director_fulltext_suite_rrh.py
    python experiments/run_director_fulltext_suite_rrh.py --dry-run
"""

import argparse
import os
import sys
from pathlib import Path

IMPLEMENTATION_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, IMPLEMENTATION_DIR)
sys.path.insert(0, os.path.join(IMPLEMENTATION_DIR, "director_agent"))

from scenarios.olaf_derailment_scenario_suite import SCENARIOS
from character_prompts.olaf import CHARACTER  # noqa: F401
from scenarios.red_riding_hood_full_text import FULL_STORY_TEXT
from director_agent.auto_main_fulltext import run_story_fulltext

CHARACTER_MODULE = "character_prompts.olaf"
SCENARIO_MODULE = "scenarios.olaf_derailment_scenario_suite"
RUN_ID = 1


def output_path(scenario_name: str) -> Path:
    return (
        Path(IMPLEMENTATION_DIR)
        / "outputs"
        / "director_agent_fulltext"
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

    scenario_names = sorted(n for n in SCENARIOS if "retells_red_riding_hood" in n)
    print(f"Suite: {len(scenario_names)} scenarios\n")

    todo = []
    for name in scenario_names:
        out = output_path(name)
        if out.exists():
            print(f"  [skip] {name}")
        else:
            todo.append(name)

    print(f"\nTo run: {len(todo)} director-fulltext scenarios")

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
        print(f"\n[director-fulltext {i}/{len(todo)}] {name}")
        try:
            path = run_story_fulltext(
                character_module=CHARACTER_MODULE,
                scenario_module=SCENARIO_MODULE,
                full_story_text=FULL_STORY_TEXT,
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
