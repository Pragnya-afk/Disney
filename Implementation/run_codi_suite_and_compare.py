"""
run_codi_suite_and_compare.py

End-to-end pipeline:
  Phase 1 – codi   : Run CoDi generation for every scenario in the suite
  Phase 2 – eval   : Pairwise LLM evaluation (CoDi vs Director)
  Phase 3 – summary: Regenerate all summary tables

Each phase is idempotent — completed work is never re-run unless --force.
All three phases run by default; use --only to run a single phase.

Usage (run from Implementation/):
  # Full pipeline
  python run_codi_suite_and_compare.py

  # Preview what would run without executing
  python run_codi_suite_and_compare.py --dry-run

  # Single phases
  python run_codi_suite_and_compare.py --only codi
  python run_codi_suite_and_compare.py --only eval
  python run_codi_suite_and_compare.py --only summary

  # Re-run everything even if outputs exist
  python run_codi_suite_and_compare.py --force

  # Use a different evaluation model
  python run_codi_suite_and_compare.py --model gpt-4o-mini

  # Use a specific CoDi generation model
  python run_codi_suite_and_compare.py --codi-model gpt-4o-mini

Output locations:
  CoDi raw outputs  : ../CoDi-main/CoDi-main/outputs/suite/{scenario}/
  CoDi transcripts  : outputs/codi/{scenario}/batch/run_{id}.json
  Eval results      : evaluation_results/{scenario}/pairwise_codi_vs_director_run_{id}.json
  Summary tables    : evaluation_summary/
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Path setup

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
CODI_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", "CoDi-main", "CoDi-main"))

sys.path.insert(0, CURRENT_DIR)
sys.path.insert(0, os.path.join(CURRENT_DIR, "evaluation_agent"))

from dotenv import load_dotenv
load_dotenv(os.path.join(CURRENT_DIR, ".env"))

from scenarios.olaf_derailment_scenario_suite import SCENARIOS
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

# Constants and Python executable detection

CHARACTER_MODULE = "character_prompts.olaf"
DEFAULT_RUN_ID = 1
DEFAULT_EVAL_MODEL = "gpt-4o"
DEFAULT_CODI_MODEL = "gpt-4o"

CODI_OUTPUTS_DIR = Path(CURRENT_DIR) / "outputs" / "codi"
DIRECTOR_OUTPUTS_DIR = Path(CURRENT_DIR) / "outputs" / "director_agent"
EVAL_RESULTS_DIR = Path(CURRENT_DIR) / "evaluation_results"

# CoDi has its own venv with required dependencies.
CODI_PYTHON = str(Path(CODI_DIR) / "venv" / "bin" / "python")
if not Path(CODI_PYTHON).exists():
    CODI_PYTHON = sys.executable  # fallback

# summarize_evaluations.py needs pandas; try a venv that has it.
try:
    import pandas  # noqa: F401
    SUMMARY_PYTHON = sys.executable
except ImportError:
    _disney_venv_python = str(Path(CURRENT_DIR).parent / ".venv" / "bin" / "python")
    SUMMARY_PYTHON = _disney_venv_python if Path(_disney_venv_python).exists() else sys.executable


# Path helpers

def codi_output_path(scenario_name: str, run_id: int) -> Path:
    return CODI_OUTPUTS_DIR / scenario_name / "batch" / f"run_{run_id}.json"


def director_output_path(scenario_name: str, run_id: int) -> Path:
    return DIRECTOR_OUTPUTS_DIR / scenario_name / "batch" / f"run_{run_id}.json"


def eval_result_path(scenario_name: str, run_id: int) -> Path:
    return EVAL_RESULTS_DIR / scenario_name / f"pairwise_codi_vs_director_run_{run_id}.json"


def codi_raw_output_dir(scenario_name: str) -> Path:
    """Staging directory for raw CoDi JSON outputs (preserved for debugging)."""
    return Path(CODI_DIR) / "outputs" / "suite" / scenario_name


# CoDi input generation

def make_codi_inputs_text(scenario: dict) -> str:
    """
    Build a natural-language 'inputs' description for CoDi from a scenario dict.
    Matches the format used in CoDi's data/example.jsonl.
    """
    story_topic = scenario["story_topic"]
    derailment_level = scenario.get("derailment_level", "none")

    character_context = (
        "Olaf, the friendly snowman from Frozen, narrates this story in his warm, "
        "playful, and enthusiastic voice. He often connects events to themes of "
        "warmth, love, and the joy of new experiences."
    )

    if derailment_level == "none":
        user_desc = (
            "The user is engaged and supportive throughout, asking on-topic questions "
            "that help move the story forward."
        )
    elif derailment_level == "medium":
        user_desc = (
            "About half of the user's inputs are completely off-topic questions unrelated "
            "to the story. Olaf should handle these gracefully and steer the narrative back "
            "on track."
        )
    else:  # complete
        user_desc = (
            "All of the user's questions are completely off-topic and unrelated to the "
            "story. Olaf should still try to guide the interaction toward a coherent, "
            "complete story despite the persistent interruptions."
        )

    return f"{character_context} {story_topic} {user_desc}"


# CoDi output → transcript conversion
# (Inlined from evaluation_agent/convert_codi_to_transcript.py to avoid
#  import-chain issues with that module's sibling imports.)

def _sort_turn_key(key: str) -> int:
    match = re.match(r"turn_(-?\d+)$", key)
    return int(match.group(1)) if match else float("inf")


def _is_end_marker(text: str) -> bool:
    if not text:
        return True
    return bool(re.match(r"^(PART|ACT|STORY)\s+\d*\s*ENDS$", text.strip(), re.IGNORECASE))


def _extract_story_progress(narrative: dict) -> List[str]:
    texts: List[str] = []

    if any(k.startswith("part_") for k in narrative):
        for part_key in sorted(
            [k for k in narrative if k.startswith("part_")],
            key=lambda k: int(k.split("_")[1]),
        ):
            part_data = narrative[part_key]
            for turn_key in sorted(
                [k for k in part_data if k.startswith("turn_")],
                key=_sort_turn_key,
            ):
                if turn_key == "turn_-1":
                    continue
                sp = part_data[turn_key].get("story_progress", "")
                if sp and not _is_end_marker(sp):
                    texts.append(sp.strip())
    else:
        for turn_key in sorted(
            [k for k in narrative if k.startswith("turn_")],
            key=_sort_turn_key,
        ):
            if turn_key == "turn_-1":
                continue
            sp = narrative[turn_key].get("story_progress", "")
            if sp and not _is_end_marker(sp):
                texts.append(sp.strip())

    return texts


def _build_transcript(
    story_texts: List[str],
    scenario_name: str,
    run_id: int,
) -> List[Dict[str, Any]]:
    transcript = []
    for idx, text in enumerate(story_texts, start=1):
        transcript.append({
            "method": "codi",
            "character": "Olaf",
            "scenario": scenario_name,
            "run_id": run_id,
            "turn_index": idx,
            "beat": f"turn_{idx}",
            "user_input": "",
            "model_output": {
                "character_response": text,
                "story_event": text,
                "animation": "",
                "beat_completed": False,
            },
        })
    return transcript


def convert_codi_json_to_transcript(
    codi_json_path: str,
    example_id: str,
    scenario_name: str,
    run_id: int,
) -> List[Dict[str, Any]]:
    """Load a raw CoDi JSON, find the matching example, and build a transcript."""
    with open(codi_json_path, encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError(f"Expected a list in {codi_json_path}, got {type(data).__name__}")

    example = next((item for item in data if item.get("example_id") == example_id), None)
    if example is None:
        ids = [item.get("example_id") for item in data]
        raise ValueError(f"example_id '{example_id}' not found. Available: {ids}")

    narrative = example.get("narrative", {})
    story_texts = _extract_story_progress(narrative)
    if not story_texts:
        raise ValueError(f"No story_progress found for example '{example_id}'.")

    return _build_transcript(story_texts, scenario_name, run_id)


# Phase 1 – CoDi generation

def _codi_raw_output_filename(codi_model: str) -> str:
    return f"gen_d_{codi_model}_c_{codi_model}.json"


def run_codi_for_scenario(
    scenario: dict,
    run_id: int,
    codi_model: str,
    dry_run: bool,
    force: bool,
) -> Optional[Path]:
    """
    Generate a CoDi output for one scenario and convert it to transcript format.
    Returns the saved transcript path, or None if skipped/failed.
    """
    scenario_name = scenario["scenario_name"]
    out_path = codi_output_path(scenario_name, run_id)

    if out_path.exists() and not force:
        print(f"  [skip] {scenario_name} — transcript already exists")
        return out_path

    if dry_run:
        print(f"  [dry]  would generate CoDi for {scenario_name}")
        return None

    raw_dir = codi_raw_output_dir(scenario_name)
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_json = raw_dir / _codi_raw_output_filename(codi_model)

    # If raw CoDi output already exists (from a previous interrupted run), skip generation.
    if not raw_json.exists() or force:
        # Write JSONL input for this scenario
        jsonl_path = raw_dir / "input.jsonl"
        with open(jsonl_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "example_id": scenario_name,
                "inputs": make_codi_inputs_text(scenario),
            }) + "\n")

        cmd = [
            CODI_PYTHON,
            "generation.py",
            "--data-file", str(jsonl_path),
            "--out-dir", str(raw_dir),
            "--planner-agent-base-model", codi_model,
            "--director-agent-base-model", codi_model,
            "--character-agent-base-model", codi_model,
            "--editor-agent-base-model", codi_model,
            "--max-turn", "100",
        ]

        codi_log_dir = str(Path(CODI_DIR) / "log")
        codi_env = {**os.environ, "LOG_DIR": codi_log_dir}

        print(f"  Running CoDi ({codi_model})…")
        try:
            result = subprocess.run(
                cmd,
                cwd=CODI_DIR,
                env=codi_env,
                timeout=900,
                capture_output=True,
                text=True,
            )
        except subprocess.TimeoutExpired:
            print(f"  ERROR: CoDi timed out for {scenario_name}")
            return None

        if result.returncode != 0:
            tail = (result.stderr or result.stdout or "")[-600:]
            print(f"  ERROR: CoDi generation failed:\n{tail}")
            return None

    if not raw_json.exists():
        # Try to find any JSON file CoDi may have written
        candidates = sorted(raw_dir.glob("gen_*.json"))
        if not candidates:
            print(f"  ERROR: no CoDi output JSON found in {raw_dir}")
            return None
        raw_json = candidates[0]
        print(f"  (using {raw_json.name})")

    # Convert raw CoDi output → transcript
    try:
        transcript = convert_codi_json_to_transcript(
            codi_json_path=str(raw_json),
            example_id=scenario_name,
            scenario_name=scenario_name,
            run_id=run_id,
        )
    except Exception as e:
        print(f"  ERROR: conversion failed — {e}")
        return None

    if not transcript:
        print(f"  ERROR: empty transcript for {scenario_name}")
        return None

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)

    print(f"  saved ({len(transcript)} turns) → {out_path}")
    return out_path


# Phase 2 – Pairwise evaluation

def _build_character_profile(scenario: dict) -> str:
    return json.dumps(
        {
            "character": OLAF_CHARACTER,
            "story_topic": scenario["story_topic"],
            "beats": scenario["beats"],
        },
        indent=2,
        ensure_ascii=False,
    )


def run_comparison_eval(
    scenario: dict,
    run_id: int,
    model: str,
    force: bool,
) -> Optional[Path]:
    """
    Run AB + BA pairwise evaluation for one scenario (CoDi vs Director).
    Returns the saved result path, or None if skipped/failed.
    """
    scenario_name = scenario["scenario_name"]
    result_path = eval_result_path(scenario_name, run_id)

    if result_path.exists() and not force:
        print(f"  [skip] {scenario_name} — eval already exists")
        return result_path

    codi_path = codi_output_path(scenario_name, run_id)
    dir_path = director_output_path(scenario_name, run_id)

    if not codi_path.exists():
        print(f"  [skip] {scenario_name} — no CoDi output")
        return None
    if not dir_path.exists():
        print(f"  [skip] {scenario_name} — no director output")
        return None

    character_profile = _build_character_profile(scenario)
    client = make_client()

    transcript_codi = load_json(str(codi_path))
    transcript_director = load_json(str(dir_path))
    story_codi = transcript_to_story(transcript_codi)
    story_director = transcript_to_story(transcript_director)

    print(f"  scoring A (codi)…")
    single_a = run_single_evaluation(client, model, story_codi, character_profile)

    print(f"  scoring B (director)…")
    single_b = run_single_evaluation(client, model, story_director, character_profile)

    print(f"  pairwise AB…")
    ab_result = run_ab_evaluation(client, model, story_codi, story_director, character_profile)

    print(f"  pairwise BA…")
    ba_result = run_ab_evaluation(client, model, story_director, story_codi, character_profile)

    ba_converted = convert_ba_to_original_labels(ba_result["winners"])
    aggregated = aggregate_ab_ba(ab_result["winners"], ba_converted)

    result = {
        "timestamp": datetime.now().isoformat(),
        "run_id": run_id,
        "scenario": scenario_name,
        "character_module": CHARACTER_MODULE,
        "story_a_path": str(codi_path),
        "story_b_path": str(dir_path),
        "model": model,
        "comparison": "codi_vs_director",
        "single_story_scores": {
            "A_codi": single_a,
            "B_director": single_b,
        },
        "ab_evaluation": ab_result,
        "ba_evaluation": ba_result,
        "ba_winners_converted_to_original_labels": ba_converted,
        "aggregated_ab_ba_winners": aggregated,
    }

    result_path.parent.mkdir(parents=True, exist_ok=True)
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"  saved → {result_path}")
    return result_path


# Phase 3 – Summary tables

def run_summary(dry_run: bool) -> None:
    if dry_run:
        print("  [dry] would regenerate summary tables")
        return

    print(f"  Using Python: {SUMMARY_PYTHON}")
    result = subprocess.run(
        [SUMMARY_PYTHON, "evaluation_agent/summarize_evaluations.py"],
        cwd=CURRENT_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  ERROR:\n{result.stderr[-600:]}")
    else:
        for line in result.stdout.strip().splitlines():
            print(f"  {line}")


# Main

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run CoDi for the full scenario suite, evaluate vs Director, and summarize."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would run without executing.")
    parser.add_argument("--only", choices=["codi", "eval", "summary"],
                        help="Run only one phase (default: all three).")
    parser.add_argument("--run-id", type=int, default=DEFAULT_RUN_ID)
    parser.add_argument("--model", default=DEFAULT_EVAL_MODEL,
                        help="LLM model for evaluation (default: gpt-4o).")
    parser.add_argument("--codi-model", default=DEFAULT_CODI_MODEL,
                        help="LLM model for CoDi generation (default: gpt-4o).")
    parser.add_argument("--force", action="store_true",
                        help="Re-run phases even if output already exists.")
    args = parser.parse_args()

    scenario_names = sorted(SCENARIOS.keys())
    sep = "=" * 60

    print(f"Suite : {len(scenario_names)} scenarios")
    print(f"Run ID: {args.run_id}")
    print(f"Models: eval={args.model}  codi={args.codi_model}")
    if args.only:
        print(f"Phase : {args.only} only")
    if args.dry_run:
        print("[DRY RUN — nothing will be executed]")

    if not args.only or args.only == "codi":
        print(f"\n{sep}")
        print("Phase 1: CoDi generation")
        print(sep)

        codi_todo = [
            n for n in scenario_names
            if not codi_output_path(n, args.run_id).exists() or args.force
        ]
        skip_count = len(scenario_names) - len(codi_todo)
        if skip_count:
            print(f"  Skipping {skip_count} scenarios with existing outputs.")
        print(f"  To generate: {len(codi_todo)}")

        codi_ok, codi_fail = 0, []
        for i, name in enumerate(codi_todo, 1):
            print(f"\n[codi {i}/{len(codi_todo)}] {name}")
            try:
                path = run_codi_for_scenario(
                    SCENARIOS[name], args.run_id, args.codi_model,
                    dry_run=args.dry_run, force=args.force,
                )
                if path:
                    codi_ok += 1
            except Exception as exc:
                print(f"  ERROR: {exc}")
                codi_fail.append((name, str(exc)))

        if not args.dry_run:
            print(f"\n  CoDi: {codi_ok}/{len(codi_todo)} succeeded, {len(codi_fail)} failed.")
            for name, err in codi_fail:
                print(f"    {name}: {err}")

    if not args.only or args.only == "eval":
        print(f"\n{sep}")
        print("Phase 2: Comparison evaluation (CoDi vs Director)")
        print(sep)

        eval_todo = []
        for name in scenario_names:
            r = eval_result_path(name, args.run_id)
            c = codi_output_path(name, args.run_id)
            d = director_output_path(name, args.run_id)
            if r.exists() and not args.force:
                print(f"  [skip] {name} — eval exists")
            elif not c.exists():
                print(f"  [skip] {name} — no CoDi output")
            elif not d.exists():
                print(f"  [skip] {name} — no director output")
            else:
                eval_todo.append(name)

        print(f"\n  To evaluate: {len(eval_todo)}")

        eval_ok, eval_fail = 0, []
        for i, name in enumerate(eval_todo, 1):
            print(f"\n[eval {i}/{len(eval_todo)}] {name}")
            if args.dry_run:
                print(f"  [dry] would evaluate {name}")
                continue
            try:
                path = run_comparison_eval(
                    SCENARIOS[name], args.run_id, args.model, args.force
                )
                if path:
                    eval_ok += 1
            except Exception as exc:
                print(f"  ERROR: {exc}")
                eval_fail.append((name, str(exc)))

        if not args.dry_run:
            print(f"\n  Eval: {eval_ok}/{len(eval_todo)} succeeded, {len(eval_fail)} failed.")
            for name, err in eval_fail:
                print(f"    {name}: {err}")

    if not args.only or args.only == "summary":
        print(f"\n{sep}")
        print("Phase 3: Summary tables")
        print(sep)
        run_summary(dry_run=args.dry_run)

    print(f"\n{sep}")
    print("Done.")
    print(sep)

    if not args.dry_run and (not args.only or args.only == "summary"):
        summary_dir = Path(CURRENT_DIR) / "evaluation_summary"
        print(f"\nTables written to: {summary_dir}")
        if summary_dir.exists():
            for f in sorted(summary_dir.glob("*.md")):
                print(f"  {f.name}")


if __name__ == "__main__":
    main()
