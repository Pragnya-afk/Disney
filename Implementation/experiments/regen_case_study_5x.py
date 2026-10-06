"""
experiments/regen_case_study_5x.py

For the two case-study scenarios (Frozen, Cinderella, complete-derailment),
generate 5 independent runs per condition and judge each with a single-story
quality score (no pairwise AB/BA -- not needed for a per-dimension average),
then average per dimension across the 5 runs. Replaces the previous n=1
hardcoded case-study data in generate_case_study_plots.py.

Conditions:
    Frozen:      baseline x5, director x5
    Cinderella:  baseline x5, director x5, time_constrained(5.0min) x5

Director is always regenerated fresh for all 5 runs (existing run_1 for both
scenarios predates the director_core.py pacing fix). Baseline and the
time-constrained track are unaffected by that fix, so existing run_1 is
reused where present and only runs 2-5 are generated fresh.

Usage (from Implementation/):
    python experiments/regen_case_study_5x.py
"""

import json
import re
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

from evaluation_agent.evaluation_core import (
    make_client,
    transcript_to_story,
    call_evaluator,
    parse_single_scores,
    BASE_DIMENSIONS,
    EVALUATE_STORY_QUALITY_PROMPT,
)
from config import JUDGE_MODEL

RUNS = [1, 2, 3, 4, 5]
CHARACTER_MODULE = "character_prompts.olaf"
SCENARIO_MODULE = "scenarios.olaf_derailment_scenario_suite"

SCENARIOS_TO_RUN = {
    "olaf_retells_frozen_1_complete_derailment": ["baseline", "director"],
    "olaf_retells_cinderella_complete_derailment": ["baseline", "director", "time5"],
}

METRICS = [
    "Plot",
    "Development",
    "Language Use",
    "Interruption Handling",
    "Character Fidelity",
    "Narrative Control",
    "Anthropomorphism",
    "Overall",
]

# Same recovery regex used earlier in this session for the judge's
# non-inline "**Dimension:**\n...\nScore: X / 10" formatting -- the parser
# bug is still unpatched, so this keeps averages from silently losing runs.
GENERAL_SCORE_RE = re.compile(r"Score:?\**\s*(\d+(?:\.\d+)?)\s*/\s*10")


def recover_scores(assessment, scores):
    """Fill missing metric scores using a looser regex over the raw judge text."""
    for m in METRICS:
        if scores.get(m) is not None:
            continue
        idx = assessment.find(m)
        window = assessment[idx : idx + 900] if idx != -1 else ""
        match = GENERAL_SCORE_RE.search(window)
        if match:
            scores[m] = float(match.group(1))
    return scores


def build_profile(scenario_name):
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


def judge_single(client, transcript_path, profile):
    """Single-story judge scores for one transcript."""
    transcript = json.loads(Path(transcript_path).read_text())
    story = transcript_to_story(transcript)
    raw = call_evaluator(
        client,
        JUDGE_MODEL,
        EVALUATE_STORY_QUALITY_PROMPT.format(character_profile=profile, story=story),
    )
    scores = parse_single_scores(raw, BASE_DIMENSIONS)
    scores = recover_scores(raw, scores)
    return scores


def path_for(cond, scenario_name, run_id):
    """Transcript path for a condition, scenario and run id."""
    if cond == "baseline":
        return (
            IMPLEMENTATION_DIR
            / "outputs"
            / "baseline"
            / scenario_name
            / "batch"
            / f"run_{run_id}.json"
        )
    if cond == "director":
        return (
            IMPLEMENTATION_DIR
            / "outputs"
            / "director_agent"
            / scenario_name
            / "batch"
            / f"run_{run_id}.json"
        )
    if cond == "time5":
        return (
            IMPLEMENTATION_DIR
            / "outputs"
            / "target_duration_director_agent"
            / scenario_name
            / "5.0min"
            / "batch"
            / f"run_{run_id}.json"
        )
    raise ValueError(cond)


def main():
    """Generate 5 runs per condition, judge them and save the averages."""
    client = make_client()
    all_results = {}

    for scenario_name, conditions in SCENARIOS_TO_RUN.items():
        profile = build_profile(scenario_name)
        scenario = SCENARIOS[scenario_name]
        all_results[scenario_name] = {}

        for cond in conditions:
            print(f"\n=== {scenario_name} / {cond} ===", flush=True)
            per_run_scores = []
            for run_id in RUNS:
                path = path_for(cond, scenario_name, run_id)

                if cond == "director":
                    print(f"  [gen] director run {run_id}", flush=True)
                    run_director(
                        character_module=CHARACTER_MODULE,
                        scenario_module=SCENARIO_MODULE,
                        run_id=run_id,
                        scenario_name_override=scenario_name,
                    )
                elif cond == "baseline":
                    if not path.exists():
                        print(f"  [gen] baseline run {run_id}", flush=True)
                        run_baseline(scenario, CHARACTER, run_id)
                    else:
                        print(f"  [reuse] baseline run {run_id}", flush=True)
                elif cond == "time5":
                    if not path.exists():
                        print(f"  [gen] time5 run {run_id}", flush=True)
                        run_time(
                            character_module=CHARACTER_MODULE,
                            scenario_module=SCENARIO_MODULE,
                            run_id=run_id,
                            time_limit=5.0,
                            scenario_name_override=scenario_name,
                        )
                    else:
                        print(f"  [reuse] time5 run {run_id}", flush=True)

                scores = judge_single(client, path, profile)
                print(f"  run {run_id} scores: {scores}", flush=True)
                per_run_scores.append(scores)

            avg = {}
            for m in METRICS:
                vals = [s[m] for s in per_run_scores if s.get(m) is not None]
                avg[m] = sum(vals) / len(vals) if vals else None
            all_results[scenario_name][cond] = {"runs": per_run_scores, "average": avg}
            print(f"  AVERAGE ({cond}): {avg}", flush=True)

    out_path = IMPLEMENTATION_DIR / "evaluation_results" / "case_study_5x_results.json"
    out_path.write_text(json.dumps(all_results, indent=2))
    print(f"\nSaved: {out_path}", flush=True)


if __name__ == "__main__":
    main()
