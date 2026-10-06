"""
experiments/run_judge_model_comparison_baseline.py

Same idea as run_judge_model_comparison.py, but for the baseline_vs_director
track instead of beats_vs_fulltext_director: reruns existing baseline-vs-
director pairwise evaluations with a different judge model, to check
whether the judge's verdict is sensitive to which model is doing the
judging. Reuses the exact same prompts/parsing as the rest of the
evaluation pipeline (evaluation_agent.evaluation_core) -- only the model
changes.

Usage (from Implementation/):
    python experiments/run_judge_model_comparison_baseline.py --model gpt-5.6-sol \
        --scenarios olaf_retells_red_riding_hood_no_derailment \
                    olaf_retells_red_riding_hood_medium_derailment \
                    olaf_retells_red_riding_hood_complete_derailment
"""

import argparse
import json
from datetime import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # Implementation/

from dotenv import load_dotenv
load_dotenv(".env")

from evaluation_agent.evaluation_core import (
    make_client,
    load_json,
    transcript_to_story,
    parse_ab_winners,
    parse_single_scores,
    convert_ba_to_original_labels,
    aggregate_ab_ba,
    BASE_DIMENSIONS,
    EVALUATE_STORY_AB_PROMPT,
    EVALUATE_STORY_QUALITY_PROMPT,
)
from scenarios.olaf_derailment_scenario_suite import SCENARIOS
from character_prompts.olaf import CHARACTER

IMPLEMENTATION_DIR = Path(__file__).parent.parent


def call_evaluator(client, model: str, prompt: str) -> str:
    """
    Same as evaluation_core.call_evaluator, but without forcing temperature=0 --
    newer reasoning-style models (gpt-5.x family) reject any explicit
    temperature other than their default (1) and error out otherwise.
    """
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a careful literary critic and evaluator of "
                    "interactive AI character stories."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content.strip()


def build_profile(scenario_name: str) -> str:
    sc = SCENARIOS[scenario_name]
    return json.dumps({
        "name": CHARACTER["name"],
        "character_prompt": CHARACTER["character_prompt"],
        "available_animations": CHARACTER["available_animations"],
        "story_topic": sc["story_topic"],
        "beats": sc["beats"],
    }, indent=2, ensure_ascii=False)


def run_single(client, model, story, profile, prompt_template, dimensions):
    raw = call_evaluator(client, model, prompt_template.format(character_profile=profile, story=story))
    scores = parse_single_scores(raw, dimensions)
    return {"assessment": raw, "scores": scores}


def run_ab_ba(client, model, story_a, story_b, profile, prompt_template, dimensions):
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


def run_one(client, model, scenario):
    path_a = IMPLEMENTATION_DIR / "outputs" / "baseline" / scenario / "batch" / "run_1.json"
    path_b = IMPLEMENTATION_DIR / "outputs" / "director_agent" / scenario / "batch" / "run_1.json"

    profile = build_profile(scenario)
    story_a = transcript_to_story(load_json(str(path_a)))
    story_b = transcript_to_story(load_json(str(path_b)))

    print(f"Judging '{scenario}' (baseline vs. director) with model={model} ...")

    single_a = run_single(client, model, story_a, profile, EVALUATE_STORY_QUALITY_PROMPT, BASE_DIMENSIONS)
    single_b = run_single(client, model, story_b, profile, EVALUATE_STORY_QUALITY_PROMPT, BASE_DIMENSIONS)
    ab_ba = run_ab_ba(client, model, story_a, story_b, profile, EVALUATE_STORY_AB_PROMPT, BASE_DIMENSIONS)

    result = {
        "timestamp": datetime.now().isoformat(),
        "story_a_path": str(path_a.relative_to(IMPLEMENTATION_DIR)),
        "story_b_path": str(path_b.relative_to(IMPLEMENTATION_DIR)),
        "scenario": scenario,
        "model": model,
        "single_story_scores": {"A": single_a, "B": single_b},
        **ab_ba,
    }

    out_dir = IMPLEMENTATION_DIR / "evaluation_results" / "baseline_vs_director" / scenario
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_model_name = model.replace("/", "_")
    out_path = out_dir / f"eval_run_1_{safe_model_name}.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"saved {out_path}")
    return result


def print_comparison(model, scenario, new_result):
    existing_path = IMPLEMENTATION_DIR / "evaluation_results" / "baseline_vs_director" / scenario / "eval_run_1.json"
    if not existing_path.exists():
        return
    gpt4o = json.loads(existing_path.read_text())
    print(f"\n=== Comparison for {scenario}: gpt-4o vs {model} ===")
    print(f"{'Dimension':25s} {'gpt-4o A':>10s} {'gpt-4o B':>10s} {'new A':>10s} {'new B':>10s}   {'gpt-4o winner':>14s} {'new winner':>12s}")
    for dim in BASE_DIMENSIONS:
        g4o_a = gpt4o["single_story_scores"]["A"]["scores"].get(dim)
        g4o_b = gpt4o["single_story_scores"]["B"]["scores"].get(dim)
        new_a = new_result["single_story_scores"]["A"]["scores"].get(dim)
        new_b = new_result["single_story_scores"]["B"]["scores"].get(dim)
        g4o_w = gpt4o.get("aggregated_ab_ba_winners", {}).get(dim)
        new_w = new_result["aggregated_ab_ba_winners"].get(dim)
        flag = "  <-- DIFFERS" if g4o_w != new_w else ""
        print(f"{dim:25s} {str(g4o_a):>10s} {str(g4o_b):>10s} {str(new_a):>10s} {str(new_b):>10s}   {str(g4o_w):>14s} {str(new_w):>12s}{flag}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="Judge model to use, e.g. gpt-5.6-sol")
    parser.add_argument("--scenarios", nargs="+", required=True, help="One or more scenario names")
    args = parser.parse_args()

    client = make_client()
    for scenario in args.scenarios:
        result = run_one(client, args.model, scenario)
        print_comparison(args.model, scenario, result)


if __name__ == "__main__":
    main()
