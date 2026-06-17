#!/usr/bin/env python3
"""
run_all_evals.py

Discovers all existing outputs and runs three evaluation tracks:
  1. baseline vs director_agent          (BASE dimensions, 8 dims)
  2. director_agent vs codi              (CODI dimensions, 11 dims)
  3. time-constrained quality + AB       (TIME dimensions, 14 dims)

Each evaluation is skipped if its output file already exists.
Safe to interrupt and restart.

After all evaluations, summarizes results into tables under evaluation_summary/.

Usage (from Implementation/):
    nohup python run_all_evals.py --model gpt-4o > eval_all.log 2>&1 &
    tail -f eval_all.log

Options:
    --model       Evaluator model (default: gpt-4o)
    --only        Run only one track: baseline, codi, time, summarize
    --dry-run     Print what would run without calling the API
"""

import os
import sys
import json
import argparse
from datetime import datetime
from itertools import combinations
from pathlib import Path

CURRENT_DIR = os.path.dirname(__file__)
sys.path.insert(0, CURRENT_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(CURRENT_DIR, ".env"))

from evaluation_agent.evaluation_core import (
    make_client,
    load_json,
    transcript_to_story,
    transcript_to_story_with_director,
    convert_codi_output_to_transcript,
    call_evaluator,
    parse_ab_winners,
    parse_single_scores,
    convert_ba_to_original_labels,
    aggregate_ab_ba,
    BASE_DIMENSIONS,
    CODI_DIMENSIONS,
    TIME_DIMENSIONS,
    EVALUATE_STORY_AB_PROMPT,
    EVALUATE_STORY_QUALITY_PROMPT,
    EVALUATE_CODI_AB_PROMPT,
    EVALUATE_CODI_QUALITY_PROMPT,
    EVALUATE_TIME_AB_PROMPT,
    EVALUATE_TIME_QUALITY_PROMPT,
)
from scenarios.olaf_derailment_scenario_suite import SCENARIOS
from character_prompts.olaf import CHARACTER

OUTPUTS_DIR = Path(CURRENT_DIR) / "outputs"
EVAL_DIR    = Path(CURRENT_DIR) / "evaluation_results"
TIME_LIMITS = [0.5, 2.0, 5.0, 10.0]


# =============================================================================
# Character profile builder
# =============================================================================

def build_profile(scenario_name: str) -> str:
    sc = SCENARIOS[scenario_name]
    return json.dumps({
        "name": CHARACTER["name"],
        "character_prompt": CHARACTER["character_prompt"],
        "available_animations": CHARACTER["available_animations"],
        "story_topic": sc["story_topic"],
        "beats": sc["beats"],
    }, indent=2, ensure_ascii=False)


# =============================================================================
# Generic AB+BA runner (used by all three tracks)
# =============================================================================

def run_ab_ba(client, model, story_a, story_b, profile, prompt_template,
              dimensions, extra_fmt=None):
    """
    Run AB then BA, aggregate, return dict with all results.
    extra_fmt: extra .format() kwargs for the prompt (e.g. label_a, label_b).
    """
    fmt = dict(character_profile=profile, story_a=story_a, story_b=story_b)
    if extra_fmt:
        fmt.update(extra_fmt)

    ab_raw  = call_evaluator(client, model, prompt_template.format(**fmt))
    ab_wins = parse_ab_winners(ab_raw, dimensions)

    fmt_ba = dict(character_profile=profile, story_a=story_b, story_b=story_a)
    if extra_fmt:
        fmt_ba.update(extra_fmt)

    ba_raw  = call_evaluator(client, model, prompt_template.format(**fmt_ba))
    ba_wins = parse_ab_winners(ba_raw, dimensions)

    ba_converted = convert_ba_to_original_labels(ba_wins)
    aggregated   = aggregate_ab_ba(ab_wins, ba_converted)

    return {
        "ab_evaluation": {"assessment": ab_raw, "winners": ab_wins},
        "ba_evaluation": {"assessment": ba_raw, "winners": ba_wins},
        "ba_winners_converted_to_original_labels": ba_converted,
        "aggregated_ab_ba_winners": aggregated,
    }


def run_single(client, model, story, profile, prompt_template, dimensions):
    raw    = call_evaluator(client, model,
                            prompt_template.format(character_profile=profile, story=story))
    scores = parse_single_scores(raw, dimensions)
    return {"assessment": raw, "scores": scores}


# =============================================================================
# Logging helper
# =============================================================================

def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# =============================================================================
# Track 1 — baseline vs director_agent
# =============================================================================

def eval_baseline_vs_director(client, model, dry_run):
    baseline_scenarios = {
        p.parent.parent.name
        for p in OUTPUTS_DIR.glob("baseline/*/batch/run_1.json")
    }
    director_scenarios = {
        p.parent.parent.name
        for p in OUTPUTS_DIR.glob("director_agent/*/batch/run_1.json")
    }
    pairs = sorted(baseline_scenarios & director_scenarios)
    log(f"[baseline vs director] {len(pairs)} matching scenarios")

    for scenario in pairs:
        out_path = EVAL_DIR / "baseline_vs_director" / scenario / "eval_run_1.json"
        if out_path.exists():
            log(f"  [skip] {scenario}")
            continue

        path_a = OUTPUTS_DIR / "baseline"       / scenario / "batch" / "run_1.json"
        path_b = OUTPUTS_DIR / "director_agent" / scenario / "batch" / "run_1.json"
        log(f"  [eval] {scenario}")

        if dry_run:
            continue

        try:
            profile  = build_profile(scenario) if scenario in SCENARIOS else "{}"
            story_a  = transcript_to_story(load_json(str(path_a)))
            story_b  = transcript_to_story(load_json(str(path_b)))

            single_a = run_single(client, model, story_a, profile,
                                  EVALUATE_STORY_QUALITY_PROMPT, BASE_DIMENSIONS)
            single_b = run_single(client, model, story_b, profile,
                                  EVALUATE_STORY_QUALITY_PROMPT, BASE_DIMENSIONS)
            ab_ba    = run_ab_ba(client, model, story_a, story_b, profile,
                                 EVALUATE_STORY_AB_PROMPT, BASE_DIMENSIONS)

            result = {
                "timestamp": datetime.now().isoformat(),
                "story_a_path": str(path_a.relative_to(CURRENT_DIR)),
                "story_b_path": str(path_b.relative_to(CURRENT_DIR)),
                "scenario": scenario,
                "model": model,
                "single_story_scores": {"A": single_a, "B": single_b},
                **ab_ba,
            }

            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
            log(f"    saved {out_path}")

        except Exception as e:
            log(f"    ERROR: {e}")


# =============================================================================
# Track 2 — director_agent vs codi
# =============================================================================

def eval_codi_vs_director(client, model, dry_run):
    director_scenarios = {
        p.parent.parent.name
        for p in OUTPUTS_DIR.glob("director_agent/*/batch/run_1.json")
    }
    codi_scenarios = {
        p.parent.parent.name
        for p in OUTPUTS_DIR.glob("codi/*/batch/run_1.json")
    }
    pairs = sorted(director_scenarios & codi_scenarios)
    log(f"[director vs codi] {len(pairs)} matching scenarios")

    for scenario in pairs:
        out_path = EVAL_DIR / "codi_vs_director" / scenario / "eval_run_1.json"
        if out_path.exists():
            log(f"  [skip] {scenario}")
            continue

        path_impl = OUTPUTS_DIR / "director_agent" / scenario / "batch" / "run_1.json"
        path_codi = OUTPUTS_DIR / "codi"           / scenario / "batch" / "run_1.json"
        log(f"  [eval] {scenario}")

        if dry_run:
            continue

        try:
            profile  = build_profile(scenario) if scenario in SCENARIOS else "{}"
            impl_transcript = load_json(str(path_impl))
            codi_transcript = convert_codi_output_to_transcript(str(path_codi))

            story_impl = transcript_to_story_with_director(impl_transcript)
            story_codi = transcript_to_story_with_director(codi_transcript)

            single_impl = run_single(client, model, story_impl, profile,
                                     EVALUATE_CODI_QUALITY_PROMPT, CODI_DIMENSIONS)
            # inject required fmt keys for CODI quality prompt
            raw_impl = call_evaluator(client, model, EVALUATE_CODI_QUALITY_PROMPT.format(
                system_name="Implementation Director Agent",
                scenario_name=scenario,
                character_name="olaf",
                character_profile=profile,
                story=story_impl,
            ))
            single_impl = {"assessment": raw_impl,
                           "scores": parse_single_scores(raw_impl, CODI_DIMENSIONS)}

            raw_codi = call_evaluator(client, model, EVALUATE_CODI_QUALITY_PROMPT.format(
                system_name="CoDi Framework",
                scenario_name=scenario,
                character_name="olaf",
                character_profile=profile,
                story=story_codi,
            ))
            single_codi = {"assessment": raw_codi,
                           "scores": parse_single_scores(raw_codi, CODI_DIMENSIONS)}

            ab_ba = run_ab_ba(
                client, model, story_impl, story_codi, profile,
                EVALUATE_CODI_AB_PROMPT, CODI_DIMENSIONS,
                extra_fmt={"scenario_name": scenario, "character_name": "olaf"},
            )

            result = {
                "timestamp": datetime.now().isoformat(),
                "story_a_path": str(path_impl.relative_to(CURRENT_DIR)),
                "story_b_path": str(path_codi.relative_to(CURRENT_DIR)),
                "scenario": scenario,
                "model": model,
                "single_story_scores": {
                    "A_director": single_impl,
                    "B_codi": single_codi,
                },
                **ab_ba,
            }

            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
            log(f"    saved {out_path}")

        except Exception as e:
            log(f"    ERROR: {e}")


# =============================================================================
# Track 3 — time-constrained
# =============================================================================

def eval_time_constrained(client, model, dry_run):
    # --- quality scoring for each individual time-limit run ---
    log("[time] quality scoring per time limit")
    for path in sorted(OUTPUTS_DIR.glob(
            "target_duration_director_agent/*/*min/batch/run_1.json")):
        parts    = path.parts
        scenario = parts[-4]   # e.g. olaf_lost_lantern_adventure_no_derailment
        time_lbl = parts[-3]   # e.g. 5.0min

        out_path = EVAL_DIR / "time_constrained" / scenario / time_lbl / "quality.json"
        if out_path.exists():
            log(f"  [skip quality] {scenario} / {time_lbl}")
            continue

        log(f"  [quality] {scenario} / {time_lbl}")
        if dry_run:
            continue

        try:
            profile = build_profile(scenario) if scenario in SCENARIOS else "{}"
            story   = transcript_to_story(load_json(str(path)))
            raw     = call_evaluator(client, model, EVALUATE_TIME_QUALITY_PROMPT.format(
                character_profile=profile, story=story,
            ))
            scores  = parse_single_scores(raw, TIME_DIMENSIONS)

            result = {
                "timestamp": datetime.now().isoformat(),
                "story_a_path": str(path.relative_to(CURRENT_DIR)),
                "scenario": scenario,
                "time_limit": time_lbl,
                "model": model,
                "single_story_scores": {
                    "A": {"assessment": raw, "scores": scores},
                },
            }

            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
            log(f"    saved {out_path}")

        except Exception as e:
            log(f"    ERROR: {e}")

    # --- AB comparisons between all time-limit pairs within each scenario ---
    log("[time] AB comparisons between time pairs")

    # Group available runs by scenario
    scenario_times: dict[str, list[str]] = {}
    for path in sorted(OUTPUTS_DIR.glob(
            "target_duration_director_agent/*/*min/batch/run_1.json")):
        parts    = path.parts
        scenario = parts[-4]
        time_lbl = parts[-3]
        scenario_times.setdefault(scenario, []).append(time_lbl)

    for scenario, time_labels in sorted(scenario_times.items()):
        if len(time_labels) < 2:
            continue

        for lbl_a, lbl_b in combinations(sorted(time_labels), 2):
            tag      = f"{lbl_a}_vs_{lbl_b}"
            out_path = EVAL_DIR / "time_constrained" / scenario / tag / "ab_eval.json"
            if out_path.exists():
                log(f"  [skip AB] {scenario} {tag}")
                continue

            path_a = OUTPUTS_DIR / "target_duration_director_agent" / scenario / lbl_a / "batch" / "run_1.json"
            path_b = OUTPUTS_DIR / "target_duration_director_agent" / scenario / lbl_b / "batch" / "run_1.json"

            if not path_a.exists() or not path_b.exists():
                continue

            log(f"  [AB] {scenario} {tag}")
            if dry_run:
                continue

            try:
                profile = build_profile(scenario) if scenario in SCENARIOS else "{}"
                story_a = transcript_to_story(load_json(str(path_a)))
                story_b = transcript_to_story(load_json(str(path_b)))

                ab_ba = run_ab_ba(
                    client, model, story_a, story_b, profile,
                    EVALUATE_TIME_AB_PROMPT, TIME_DIMENSIONS,
                    extra_fmt={"label_a": lbl_a, "label_b": lbl_b},
                )

                result = {
                    "timestamp": datetime.now().isoformat(),
                    "story_a_path": str(path_a.relative_to(CURRENT_DIR)),
                    "story_b_path": str(path_b.relative_to(CURRENT_DIR)),
                    "scenario": scenario,
                    "label_a": lbl_a,
                    "label_b": lbl_b,
                    "model": model,
                    **ab_ba,
                }

                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
                log(f"    saved {out_path}")

            except Exception as e:
                log(f"    ERROR: {e}")


# =============================================================================
# Summarize
# =============================================================================

def run_summarize():
    log("[summarize] building tables...")
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "evaluation_agent.summarize_evaluations",
         "--input_dir",  str(EVAL_DIR),
         "--output_dir", str(Path(CURRENT_DIR) / "evaluation_summary")],
        cwd=CURRENT_DIR,
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model",   default="gpt-4o")
    parser.add_argument("--only",    choices=["baseline", "codi", "time", "summarize"],
                        default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    log(f"=== run_all_evals | model={args.model} | dry_run={args.dry_run} ===")

    client = None if args.dry_run else make_client()

    if args.only in (None, "baseline"):
        eval_baseline_vs_director(client, args.model, args.dry_run)

    if args.only in (None, "codi"):
        eval_codi_vs_director(client, args.model, args.dry_run)

    if args.only in (None, "time"):
        eval_time_constrained(client, args.model, args.dry_run)

    if args.only in (None, "summarize"):
        if not args.dry_run:
            run_summarize()
        else:
            log("[summarize] skipped (dry-run)")

    log("=== done ===")


if __name__ == "__main__":
    main()
