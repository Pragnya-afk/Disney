"""
run_full_suite.py

Run all scenarios in the suite for:
  - director_agent (no time limit)
  - target_duration_director_agent at 0.5, 2.0, 5.0, and 10.0 minutes

Skips any scenario/time-limit combination whose output file already exists.
Safe to interrupt and restart — completed runs are never re-run.

Usage (run from Implementation/):
    python run_full_suite.py
    python run_full_suite.py --dry-run        # print what would run, do nothing
    python run_full_suite.py --only director  # only run director_agent
    python run_full_suite.py --only time      # only run time-constrained
"""

import argparse
import os
import sys
from pathlib import Path

CURRENT_DIR = os.path.dirname(__file__)
sys.path.insert(0, CURRENT_DIR)
sys.path.insert(0, os.path.join(CURRENT_DIR, "director_agent"))
sys.path.insert(0, os.path.join(CURRENT_DIR, "director_agent", "time_constrained"))

from scenarios.olaf_derailment_scenario_suite import SCENARIOS
from director_agent.auto_main import run_story as run_director
from director_agent.time_constrained.time_auto_main import run_story as run_time

CHARACTER = "character_prompts.olaf"
SCENARIO_MODULE = "scenarios.olaf_derailment_scenario_suite"
TIME_LIMITS = [0.5, 2.0, 5.0, 10.0]
RUN_ID = 1


def director_output_path(scenario_name: str) -> Path:
    return Path(CURRENT_DIR) / "outputs" / "director_agent" / scenario_name / "batch" / f"run_{RUN_ID}.json"


def time_output_path(scenario_name: str, time_limit: float) -> Path:
    return Path(CURRENT_DIR) / "outputs" / "target_duration_director_agent" / scenario_name / f"{time_limit}min" / "batch" / f"run_{RUN_ID}.json"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print what would run without executing.")
    parser.add_argument("--only", choices=["director", "time"], default=None, help="Run only one method.")
    args = parser.parse_args()

    scenario_names = sorted(SCENARIOS.keys())
    print(f"Suite: {len(scenario_names)} scenarios")
    print(f"Time limits: {TIME_LIMITS}")
    print()

    director_todo = []
    time_todo = []

    for name in scenario_names:
        if not args.only or args.only == "director":
            out = director_output_path(name)
            if out.exists():
                print(f"  [skip] director / {name}")
            else:
                director_todo.append(name)

        if not args.only or args.only == "time":
            for tl in TIME_LIMITS:
                out = time_output_path(name, tl)
                if out.exists():
                    print(f"  [skip] time {tl}min / {name}")
                else:
                    time_todo.append((name, tl))

    total = len(director_todo) + len(time_todo)
    print(f"\nTo run: {len(director_todo)} director + {len(time_todo)} time-constrained = {total} total")

    if args.dry_run:
        print("\n-- dry run, not executing --")
        for name in director_todo:
            print(f"  director / {name}")
        for name, tl in time_todo:
            print(f"  time {tl}min / {name}")
        return

    if total == 0:
        print("Nothing to run.")
        return

    completed = 0
    failed = []

    # ── Director runs ──────────────────────────────────────────────
    for i, name in enumerate(director_todo, 1):
        label = f"[director {i}/{len(director_todo)}] {name}"
        print(f"\n{label}")
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
            failed.append((label, str(e)))

    # ── Time-constrained runs ──────────────────────────────────────
    for i, (name, tl) in enumerate(time_todo, 1):
        label = f"[time {tl}min {i}/{len(time_todo)}] {name}"
        print(f"\n{label}")
        try:
            path = run_time(
                character_module=CHARACTER,
                scenario_module=SCENARIO_MODULE,
                run_id=RUN_ID,
                time_limit=tl,
                scenario_name_override=name,
            )
            print(f"  saved: {path}")
            completed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed.append((label, str(e)))

    print(f"\n{'='*60}")
    print(f"Done. {completed}/{total} succeeded, {len(failed)} failed.")
    if failed:
        print("\nFailed runs:")
        for label, err in failed:
            print(f"  {label}: {err}")


if __name__ == "__main__":
    main()
