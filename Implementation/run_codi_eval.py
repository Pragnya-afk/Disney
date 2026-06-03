"""
run_codi_eval.py

Runs pairwise evaluation comparing CoDi outputs against corresponding
director-agent outputs.

Discovery:
  - Scans outputs/codi/ for available scenarios.
  - For each scenario, looks for a matching director-agent output.
  - Tries exact folder-name match first, then common name transformations.

Results are saved to:
  evaluation_results/{scenario_name}/pairwise_codi_vs_director_run_{id}.json

These files are automatically picked up by summarize_evaluations.py
(python evaluation_agent/summarize_evaluations.py) when regenerating
the evaluation summary tables.

Usage (run from Implementation/):
    python run_codi_eval.py
    python run_codi_eval.py --dry-run
    python run_codi_eval.py --scenario noderail_red_riding_hood
    python run_codi_eval.py --run-id 1 --model gpt-4o
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CURRENT_DIR)
sys.path.insert(0, os.path.join(CURRENT_DIR, "evaluation_agent"))

from dotenv import load_dotenv
load_dotenv(os.path.join(CURRENT_DIR, ".env"))

from character_prompts.olaf import CHARACTER as OLAF_CHARACTER
from evaluation_agent.evaluation_core import (
    make_client,
    load_json,
    transcript_to_story,
    run_single_evaluation,
    run_ab_evaluation,
    convert_ba_to_original_labels,
    aggregate_ab_ba,
)

CHARACTER_MODULE = "character_prompts.olaf"
DEFAULT_RUN_ID = 1
DEFAULT_EVAL_MODEL = "gpt-4o"

CODI_OUTPUTS_DIR = Path(CURRENT_DIR) / "outputs" / "codi"
DIRECTOR_OUTPUTS_DIR = Path(CURRENT_DIR) / "outputs" / "director_agent"
EVAL_RESULTS_DIR = Path(CURRENT_DIR) / "evaluation_results"


# ── Scenario matching ──────────────────────────────────────────────────────────

# Maps common CoDi scenario name patterns to director-agent folder names.
# Add entries here when CoDi covers scenarios with different naming conventions.
SCENARIO_ALIAS_MAP = {
    "noderail_red_riding_hood": "olaf_retells_red_riding_hood_no_derailment",
    "complete_derail_red_riding_hood": "olaf_retells_red_riding_hood_complete_derailment",
    "medium_derail_red_riding_hood": "olaf_retells_red_riding_hood_medium_derailment",
}


def find_director_output(scenario_name: str, run_id: int) -> Path | None:
    """Return path to matching director output, or None if not found."""
    candidates = [scenario_name]

    # Try alias map
    if scenario_name in SCENARIO_ALIAS_MAP:
        candidates.append(SCENARIO_ALIAS_MAP[scenario_name])

    # Common transformations: noderail_ prefix → no_derailment suffix
    if scenario_name.startswith("noderail_"):
        base = scenario_name[len("noderail_"):]
        candidates += [
            f"{base}_no_derailment",
            f"olaf_retells_{base}_no_derailment",
            f"olaf_{base}_no_derailment",
        ]
    if scenario_name.startswith("complete_derail_"):
        base = scenario_name[len("complete_derail_"):]
        candidates += [
            f"{base}_complete_derailment",
            f"olaf_retells_{base}_complete_derailment",
        ]
    if scenario_name.startswith("medium_derail_"):
        base = scenario_name[len("medium_derail_"):]
        candidates += [
            f"{base}_medium_derailment",
            f"olaf_retells_{base}_medium_derailment",
        ]

    for cand in candidates:
        path = DIRECTOR_OUTPUTS_DIR / cand / "batch" / f"run_{run_id}.json"
        if path.exists():
            return path

    return None


# ── Scenario context loading ───────────────────────────────────────────────────

def load_scenario_context(scenario_name: str) -> dict | None:
    """Try to load story_topic and beats from a scenarios module."""
    import importlib

    candidates = [
        f"scenarios.{scenario_name}",
        # alias-mapped name as module
        f"scenarios.{SCENARIO_ALIAS_MAP.get(scenario_name, '')}",
    ]

    for module_name in candidates:
        if not module_name or module_name == "scenarios.":
            continue
        try:
            mod = importlib.import_module(module_name)
            scenario = mod.SCENARIO
            return {"story_topic": scenario["story_topic"], "beats": scenario["beats"]}
        except (ImportError, AttributeError):
            continue

    # Also try loading from the suite via the director-matched name
    try:
        from scenarios.olaf_derailment_scenario_suite import SCENARIOS
        for name, sc in SCENARIOS.items():
            if scenario_name in name or SCENARIO_ALIAS_MAP.get(scenario_name, "") == name:
                return {"story_topic": sc["story_topic"], "beats": sc["beats"]}
    except ImportError:
        pass

    return None


def build_character_profile(scenario_name: str) -> str:
    scenario_context = load_scenario_context(scenario_name)
    payload = {"character": OLAF_CHARACTER}
    if scenario_context:
        payload["story_topic"] = scenario_context["story_topic"]
        payload["beats"] = scenario_context["beats"]
    return json.dumps(payload, indent=2, ensure_ascii=False)


# ── Evaluation runner ──────────────────────────────────────────────────────────

def run_codi_eval(
    codi_path: Path,
    director_path: Path,
    scenario_name: str,
    run_id: int,
    model: str,
) -> Path:
    """Run pairwise CoDi (A) vs Director (B) evaluation for one scenario."""
    character_profile = build_character_profile(scenario_name)
    client = make_client()

    transcript_codi = load_json(str(codi_path))
    transcript_director = load_json(str(director_path))
    story_codi = transcript_to_story(transcript_codi)
    story_director = transcript_to_story(transcript_director)

    print(f"  [eval] scoring A (codi)…")
    single_a = run_single_evaluation(client, model, story_codi, character_profile)

    print(f"  [eval] scoring B (director)…")
    single_b = run_single_evaluation(client, model, story_director, character_profile)

    print(f"  [eval] pairwise AB…")
    ab_result = run_ab_evaluation(client, model, story_codi, story_director, character_profile)

    print(f"  [eval] pairwise BA…")
    ba_result = run_ab_evaluation(client, model, story_director, story_codi, character_profile)

    ba_converted = convert_ba_to_original_labels(ba_result["winners"])
    aggregated = aggregate_ab_ba(ab_result["winners"], ba_converted)

    result = {
        "timestamp": datetime.now().isoformat(),
        "run_id": run_id,
        "scenario": scenario_name,
        "character_module": CHARACTER_MODULE,
        "story_a_path": str(codi_path),
        "story_b_path": str(director_path),
        "model": model,
        "comparison": "codi_vs_director",
        "single_story_scores": {"A": single_a, "B": single_b},
        "ab_evaluation": ab_result,
        "ba_evaluation": ba_result,
        "ba_winners_converted_to_original_labels": ba_converted,
        "aggregated_ab_ba_winners": aggregated,
    }

    result_dir = EVAL_RESULTS_DIR / scenario_name
    result_dir.mkdir(parents=True, exist_ok=True)
    out_path = result_dir / f"pairwise_codi_vs_director_run_{run_id}.json"

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"  [eval] saved → {out_path}")
    return out_path


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Evaluate CoDi outputs against director-agent outputs."
    )
    parser.add_argument("--dry-run", action="store_true", help="Show plan without running.")
    parser.add_argument("--run-id", type=int, default=DEFAULT_RUN_ID, help="Run ID to evaluate.")
    parser.add_argument("--model", default=DEFAULT_EVAL_MODEL, help="Evaluator model.")
    parser.add_argument("--scenario", default=None, help="Evaluate only this CoDi scenario folder.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run evaluation even if result already exists.",
    )
    args = parser.parse_args()

    if not CODI_OUTPUTS_DIR.exists():
        print(f"No CoDi outputs directory: {CODI_OUTPUTS_DIR}")
        return

    # Discover CoDi scenarios
    items = []
    for scenario_dir in sorted(CODI_OUTPUTS_DIR.iterdir()):
        if not scenario_dir.is_dir():
            continue
        scenario_name = scenario_dir.name
        if args.scenario and scenario_name != args.scenario:
            continue

        codi_path = scenario_dir / "batch" / f"run_{args.run_id}.json"
        if not codi_path.exists():
            print(f"  [skip] missing CoDi output: {codi_path}")
            continue

        director_path = find_director_output(scenario_name, args.run_id)
        eval_out = EVAL_RESULTS_DIR / scenario_name / f"pairwise_codi_vs_director_run_{args.run_id}.json"

        items.append({
            "scenario_name": scenario_name,
            "codi_path": codi_path,
            "director_path": director_path,
            "eval_out": eval_out,
        })

    print(f"CoDi scenarios found: {len(items)}\n")
    for item in items:
        status = "READY" if item["director_path"] else "NO_DIRECTOR"
        done = " [done]" if item["eval_out"].exists() else ""
        print(f"  [{status}] {item['scenario_name']}{done}")
        if not item["director_path"]:
            print(f"           -> No matching director output in {DIRECTOR_OUTPUTS_DIR}")
            print(f"              Run the director on this scenario first, or add an alias to SCENARIO_ALIAS_MAP.")

    if args.dry_run:
        print("\n-- dry run, stopping here --")
        return

    ready = [i for i in items if i["director_path"]]
    to_run = [i for i in ready if args.force or not i["eval_out"].exists()]

    print(f"\n{len(ready)} scenarios have director outputs; {len(to_run)} need evaluation.\n")

    completed, failed = 0, []
    for i, item in enumerate(to_run, 1):
        print(f"[{i}/{len(to_run)}] {item['scenario_name']}")
        try:
            run_codi_eval(
                codi_path=item["codi_path"],
                director_path=item["director_path"],
                scenario_name=item["scenario_name"],
                run_id=args.run_id,
                model=args.model,
            )
            completed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed.append((item["scenario_name"], str(e)))

    print(f"\n{'='*60}")
    print(f"Done. {completed}/{len(to_run)} succeeded, {len(failed)} failed.")
    if failed:
        print("\nFailed:")
        for name, err in failed:
            print(f"  {name}: {err}")

    if completed > 0:
        print("\nRegenerate summary tables:")
        print("  python evaluation_agent/summarize_evaluations.py")


if __name__ == "__main__":
    main()
