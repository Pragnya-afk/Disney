#!/usr/bin/env python3
"""
run_complete_pipeline.py

Master pipeline — runs ALL evaluation stages end-to-end:

  Phase 1 – baseline : Baseline for ALL 30 suite scenarios (skip existing)
  Phase 2 – director : Director + time-constrained runs (skip existing)
  Phase 3 – codi     : CoDi generation for ALL 30 scenarios (skip existing)
  Phase 4 – eval     : All evaluation tracks + summary tables
                         · baseline vs director  (BASE_DIMENSIONS, 8 dims)
                         · director vs codi      (CODI_DIMENSIONS, 11 dims)
                         · time 0.5/2/5/10 min   (TIME_DIMENSIONS, 14 dims)
                         · CSV / Markdown / LaTeX tables

Every phase is idempotent — completed work is never re-run.
Safe to interrupt and restart.

Usage (from Implementation/):
    nohup python3 run_complete_pipeline.py > pipeline.log 2>&1 &
    tail -f pipeline.log

Options:
    --model    LLM evaluator model (default: gpt-4o)
    --only     Run only one phase: baseline | director | codi | eval
    --dry-run  Print what would run without calling the API or generating stories
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

CURRENT_DIR = Path(__file__).parent


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def run_phase(label: str, script_args: list[str]) -> int:
    bar = "=" * 60
    log(bar)
    log(f"PHASE: {label}")
    log(bar)
    result = subprocess.run(
        [sys.executable] + script_args,
        cwd=str(CURRENT_DIR),
    )
    if result.returncode != 0:
        log(f"  WARNING: phase '{label}' exited with code {result.returncode}")
    log(f"  phase '{label}' finished (rc={result.returncode})")
    return result.returncode


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Run the complete Disney evaluation pipeline end-to-end."
    )
    parser.add_argument("--model", default="gpt-4o",
                        help="LLM model for evaluation (default: gpt-4o)")
    parser.add_argument("--only",
                        choices=["baseline", "director", "codi", "eval"],
                        default=None,
                        help="Run only one phase (default: all four)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Pass --dry-run to every sub-script")
    args = parser.parse_args()

    dry = ["--dry-run"] if args.dry_run else []

    log(f"=== run_complete_pipeline | model={args.model} | dry_run={args.dry_run} ===")

    # ------------------------------------------------------------------
    # Phase 1 — Baseline
    # Runs baseline for all 30 suite scenarios.
    # Uses run_baseline_suite.py which extends run_noderail_baseline_and_eval.py
    # to cover medium- and complete-derailment scenarios as well.
    # ------------------------------------------------------------------
    if args.only in (None, "baseline"):
        run_phase(
            "Baseline — all 30 scenarios",
            ["run_baseline_suite.py"] + dry,
        )

    # ------------------------------------------------------------------
    # Phase 2 — Director + Time-Constrained
    # Runs any missing director and target-duration runs.
    # All 30 × 4-time-limit = 120 runs are already done; this is a
    # safety pass that will skip everything already completed.
    # ------------------------------------------------------------------
    if args.only in (None, "director"):
        run_phase(
            "Director + Time-Constrained — all 30 scenarios × 4 time limits",
            ["run_full_suite.py"] + dry,
        )

    # ------------------------------------------------------------------
    # Phase 3 — CoDi Generation
    # Calls run_codi_suite_and_compare.py --only codi which generates
    # CoDi outputs for every scenario not yet done.
    # CoDi outputs land in outputs/codi/{scenario}/batch/run_1.json.
    # ------------------------------------------------------------------
    if args.only in (None, "codi"):
        run_phase(
            "CoDi Generation — all 30 scenarios",
            ["run_codi_suite_and_compare.py", "--only", "codi"] + dry,
        )

    # ------------------------------------------------------------------
    # Phase 4 — Evaluations + Summary Tables
    # run_all_evals.py discovers all existing outputs automatically and
    # runs three evaluation tracks (skipping already-evaluated pairs):
    #   · baseline vs director  → evaluation_results/baseline_vs_director/
    #   · director vs codi      → evaluation_results/codi_vs_director/
    #   · time quality + AB     → evaluation_results/time_constrained/
    # Then generates tables under evaluation_summary/:
    #   table_scores_by_metric.{csv,md,tex}
    #   table_scores_by_scenario.{csv,md,tex}
    #   table_derailment_robustness.{csv,md,tex}
    #   table_pairwise_wins.{csv,md,tex}
    # ------------------------------------------------------------------
    if args.only in (None, "eval"):
        run_phase(
            "Evaluations (all tracks) + Summary Tables",
            ["run_all_evals.py", "--model", args.model] + dry,
        )

    log("=== pipeline complete ===")


if __name__ == "__main__":
    main()
