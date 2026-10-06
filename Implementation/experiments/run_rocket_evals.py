"""
experiments/run_rocket_evals.py

baseline vs director evaluation track (BASE_DIMENSIONS) for the
Rocket red-riding-hood derailment suite. Mirrors the
eval_baseline_vs_director track in run_all_evals.py (which is
hardcoded to Olaf's SCENARIOS/CHARACTER) but scoped to rocket_*
scenarios / character_prompts.rocket, so it can run standalone
without touching the existing Olaf pipeline.

Writes into the same evaluation_results/baseline_vs_director/ tree,
so evaluation_agent.summarize_evaluations picks these rows up
automatically alongside the existing Olaf results.

Usage (from Implementation/):
    python experiments/run_rocket_evals.py --model gpt-4o
    python experiments/run_rocket_evals.py --dry-run
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

IMPLEMENTATION_DIR = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, IMPLEMENTATION_DIR)

from dotenv import load_dotenv

load_dotenv(os.path.join(IMPLEMENTATION_DIR, ".env"))

from evaluation_agent.evaluation_core import (
    make_client,
    load_json,
    transcript_to_story,
    call_evaluator,
    parse_ab_winners,
    parse_single_scores,
    convert_ba_to_original_labels,
    aggregate_ab_ba,
    BASE_DIMENSIONS,
    EVALUATE_STORY_AB_PROMPT,
    EVALUATE_STORY_QUALITY_PROMPT,
)
from scenarios.rocket_retells_red_riding_hood_scenario_suite import SCENARIOS
from character_prompts.rocket import CHARACTER
from config import JUDGE_MODEL

OUTPUTS_DIR = Path(IMPLEMENTATION_DIR) / "outputs"
EVAL_DIR = Path(IMPLEMENTATION_DIR) / "evaluation_results"


def log(msg: str):
    """Timestamped progress print."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def build_profile(scenario_name: str) -> str:
    """Character + scenario profile JSON for the judge."""
    sc = SCENARIOS[scenario_name]
    return json.dumps(
        {
            "name": CHARACTER["name"],
            "character_prompt": CHARACTER["character_prompt"],
            "available_animations": CHARACTER["available_animations"],
            "story_topic": sc["story_topic"],
            "beats": sc["beats"],
        },
        indent=2,
        ensure_ascii=False,
    )


def run_ab_ba(client, model, story_a, story_b, profile, prompt_template, dimensions):
    """Run AB then BA judge calls and aggregate them."""
    fmt = dict(character_profile=profile, story_a=story_a, story_b=story_b)
    ab_raw = call_evaluator(client, model, prompt_template.format(**fmt))
    ab_wins = parse_ab_winners(ab_raw, dimensions)

    fmt_ba = dict(character_profile=profile, story_a=story_b, story_b=story_a)
    ba_raw = call_evaluator(client, model, prompt_template.format(**fmt_ba))
    ba_wins = parse_ab_winners(ba_raw, dimensions)

    ba_converted = convert_ba_to_original_labels(ba_wins)
    aggregated = aggregate_ab_ba(ab_wins, ba_converted)

    return {
        "ab_evaluation": {"assessment": ab_raw, "winners": ab_wins},
        "ba_evaluation": {"assessment": ba_raw, "winners": ba_wins},
        "ba_winners_converted_to_original_labels": ba_converted,
        "aggregated_ab_ba_winners": aggregated,
    }


def run_single(client, model, story, profile, prompt_template, dimensions):
    """Single-story judge call; returns raw text and scores."""
    raw = call_evaluator(
        client, model, prompt_template.format(character_profile=profile, story=story)
    )
    scores = parse_single_scores(raw, dimensions)
    return {"assessment": raw, "scores": scores}


def eval_baseline_vs_director(client, model, dry_run):
    """Baseline vs. director for every Rocket scenario with both outputs."""
    baseline_scenarios = {
        p.parent.parent.name for p in OUTPUTS_DIR.glob("baseline/rocket_*/batch/run_1.json")
    }
    director_scenarios = {
        p.parent.parent.name for p in OUTPUTS_DIR.glob("director_agent/rocket_*/batch/run_1.json")
    }
    pairs = sorted(baseline_scenarios & director_scenarios)
    log(f"[baseline vs director / rocket] {len(pairs)} matching scenarios")

    for scenario in pairs:
        out_path = EVAL_DIR / "baseline_vs_director" / scenario / "eval_run_1.json"
        if out_path.exists():
            log(f"  [skip] {scenario}")
            continue

        path_a = OUTPUTS_DIR / "baseline" / scenario / "batch" / "run_1.json"
        path_b = OUTPUTS_DIR / "director_agent" / scenario / "batch" / "run_1.json"
        log(f"  [eval] {scenario}")

        if dry_run:
            continue

        try:
            profile = build_profile(scenario) if scenario in SCENARIOS else "{}"
            story_a = transcript_to_story(load_json(str(path_a)))
            story_b = transcript_to_story(load_json(str(path_b)))

            single_a = run_single(
                client, model, story_a, profile, EVALUATE_STORY_QUALITY_PROMPT, BASE_DIMENSIONS
            )
            single_b = run_single(
                client, model, story_b, profile, EVALUATE_STORY_QUALITY_PROMPT, BASE_DIMENSIONS
            )
            ab_ba = run_ab_ba(
                client, model, story_a, story_b, profile, EVALUATE_STORY_AB_PROMPT, BASE_DIMENSIONS
            )

            result = {
                "timestamp": datetime.now().isoformat(),
                "story_a_path": str(path_a.relative_to(IMPLEMENTATION_DIR)),
                "story_b_path": str(path_b.relative_to(IMPLEMENTATION_DIR)),
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


def run_summarize():
    """Rebuild evaluation_summary/ tables."""
    log("[summarize] building tables...")
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "evaluation_agent.summarize_evaluations",
            "--input_dir",
            str(EVAL_DIR),
            "--output_dir",
            str(Path(IMPLEMENTATION_DIR) / "evaluation_summary"),
        ],
        cwd=IMPLEMENTATION_DIR,
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=JUDGE_MODEL)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-summarize", action="store_true")
    args = parser.parse_args()

    log(f"=== run_rocket_evals | model={args.model} | dry_run={args.dry_run} ===")
    client = None if args.dry_run else make_client()

    eval_baseline_vs_director(client, args.model, args.dry_run)

    if not args.dry_run and not args.no_summarize:
        run_summarize()

    log("=== done ===")


if __name__ == "__main__":
    main()
