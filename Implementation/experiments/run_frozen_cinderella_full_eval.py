"""
experiments/run_frozen_cinderella_full_eval.py

Generates baseline / director / time-constrained transcripts, then runs the
LLM-as-judge evaluation, for exactly the two full-story scenarios used in
the user study ("olaf_retells_frozen_1" and "olaf_retells_cinderella"),
across all 7 derailment-level variants each -- mirroring how every other
scenario family in the suite was evaluated.

Scoped deliberately to just these 14 scenario names so it does not touch
the other ~47 scenario variants elsewhere in the suite that have no
transcripts yet.

Usage (from Implementation/):
    python experiments/run_frozen_cinderella_full_eval.py --dry-run
    python experiments/run_frozen_cinderella_full_eval.py
    python experiments/run_frozen_cinderella_full_eval.py --only generate
    python experiments/run_frozen_cinderella_full_eval.py --only evaluate
"""

import argparse
import sys
from pathlib import Path

IMPLEMENTATION_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(IMPLEMENTATION_DIR))
sys.path.insert(0, str(IMPLEMENTATION_DIR / "director_agent"))
sys.path.insert(0, str(IMPLEMENTATION_DIR / "director_agent" / "time_constrained"))

from dotenv import load_dotenv

load_dotenv(str(IMPLEMENTATION_DIR / ".env"))

from scenarios.olaf_derailment_scenario_suite import SCENARIOS
from character_prompts.olaf import CHARACTER
from run_baseline_suite import run_baseline
from director_agent.auto_main import run_story as run_director
from director_agent.time_constrained.time_auto_main import run_story as run_time
from config import JUDGE_MODEL

RUN_ID = 1
TIME_LIMITS = [0.5, 2.0, 5.0, 10.0]
CHARACTER_MODULE = "character_prompts.olaf"
SCENARIO_MODULE = "scenarios.olaf_derailment_scenario_suite"

TARGET_NAMES = sorted(
    n
    for n in SCENARIOS
    if n.startswith("olaf_retells_frozen_1") or n.startswith("olaf_retells_cinderella")
)


def baseline_path(name):
    return IMPLEMENTATION_DIR / "outputs" / "baseline" / name / "batch" / f"run_{RUN_ID}.json"


def director_path(name):
    return IMPLEMENTATION_DIR / "outputs" / "director_agent" / name / "batch" / f"run_{RUN_ID}.json"


def time_path(name, tl):
    return (
        IMPLEMENTATION_DIR
        / "outputs"
        / "target_duration_director_agent"
        / name
        / f"{tl}min"
        / "batch"
        / f"run_{RUN_ID}.json"
    )


def generate(dry_run: bool):
    print(f"Target scenarios ({len(TARGET_NAMES)}):")
    for n in TARGET_NAMES:
        print(f"  {n}")

    baseline_todo = [n for n in TARGET_NAMES if not baseline_path(n).exists()]
    director_todo = [n for n in TARGET_NAMES if not director_path(n).exists()]
    time_todo = [
        (n, tl) for n in TARGET_NAMES for tl in TIME_LIMITS if not time_path(n, tl).exists()
    ]

    print(
        f"\nTo run: {len(baseline_todo)} baseline, {len(director_todo)} director, "
        f"{len(time_todo)} time-constrained"
    )

    if dry_run:
        return

    failed = []

    for i, name in enumerate(baseline_todo, 1):
        print(f"\n[baseline {i}/{len(baseline_todo)}] {name}")
        try:
            run_baseline(SCENARIOS[name], CHARACTER, RUN_ID)
        except Exception as e:
            print(f"  ERROR: {e}")
            failed.append(("baseline", name, str(e)))

    for i, name in enumerate(director_todo, 1):
        print(f"\n[director {i}/{len(director_todo)}] {name}")
        try:
            path = run_director(
                character_module=CHARACTER_MODULE,
                scenario_module=SCENARIO_MODULE,
                run_id=RUN_ID,
                scenario_name_override=name,
            )
            print(f"  saved: {path}")
        except Exception as e:
            print(f"  ERROR: {e}")
            failed.append(("director", name, str(e)))

    for i, (name, tl) in enumerate(time_todo, 1):
        print(f"\n[time {tl}min {i}/{len(time_todo)}] {name}")
        try:
            path = run_time(
                character_module=CHARACTER_MODULE,
                scenario_module=SCENARIO_MODULE,
                run_id=RUN_ID,
                time_limit=tl,
                scenario_name_override=name,
            )
            print(f"  saved: {path}")
        except Exception as e:
            print(f"  ERROR: {e}")
            failed.append(("time", f"{name}@{tl}min", str(e)))

    print(f"\n{'='*60}")
    print(f"Generation done. {len(failed)} failed.")
    for kind, name, err in failed:
        print(f"  [{kind}] {name}: {err}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", choices=["generate", "evaluate"], default=None)
    parser.add_argument("--model", default=JUDGE_MODEL)
    args = parser.parse_args()

    if args.only in (None, "generate"):
        generate(args.dry_run)

    if args.only in (None, "evaluate"):
        if args.dry_run:
            print(
                "\n(dry-run) would now run: python run_all_evals.py --model "
                f"{args.model} --only baseline / --only time / --only summarize"
            )
        else:
            import subprocess

            for track in ("baseline", "time", "summarize"):
                print(f"\n{'='*60}\nEvaluation track: {track}\n{'='*60}")
                subprocess.run(
                    [
                        sys.executable,
                        "experiments/run_all_evals.py",
                        "--model",
                        args.model,
                        "--only",
                        track,
                    ],
                    cwd=str(IMPLEMENTATION_DIR),
                    check=False,
                )


if __name__ == "__main__":
    main()
