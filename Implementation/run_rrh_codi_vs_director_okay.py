"""
run_rrh_codi_vs_director_okay.py

Compare CoDi vs Director on the Red Riding Hood (no-derailment) scenario
where the Director receives only "okay" as the user input for every turn
(i.e., the story is driven entirely by the system, not the user).

CoDi generates the story autonomously — no per-turn user inputs needed.
Director is run fresh with ["okay", "okay", ...] until all beats complete.

Outputs
-------
Director transcript : outputs/director_agent/olaf_retells_red_riding_hood_no_derailment/okay_inputs/run_1.json
CoDi transcript     : outputs/codi/olaf_retells_red_riding_hood_no_derailment/batch/run_1.json  (existing)
Eval result         : evaluation_results/olaf_retells_red_riding_hood_no_derailment/pairwise_codi_vs_director_okay.json

Usage
-----
    python run_rrh_codi_vs_director_okay.py
    python run_rrh_codi_vs_director_okay.py --skip-director  # reuse existing director okay run
    python run_rrh_codi_vs_director_okay.py --skip-eval      # only (re)generate transcripts
    python run_rrh_codi_vs_director_okay.py --model gpt-4o   # evaluation model
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Paths

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DIRECTOR_AGENT_DIR = os.path.join(CURRENT_DIR, "director_agent")
EVAL_AGENT_DIR = os.path.join(CURRENT_DIR, "evaluation_agent")

sys.path.insert(0, CURRENT_DIR)
sys.path.insert(0, DIRECTOR_AGENT_DIR)
sys.path.insert(0, EVAL_AGENT_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(CURRENT_DIR, ".env"))

from openai import OpenAI

# Load scenario and character

from scenarios.olaf_derailment_scenario_suite import SCENARIOS
from character_prompts.olaf import CHARACTER as OLAF_CHARACTER

SCENARIO_NAME = "olaf_retells_red_riding_hood_no_derailment"
SCENARIO = SCENARIOS[SCENARIO_NAME]
OKAY_INPUTS = ["okay"] * 30  # more than enough for all beats to complete

DIRECTOR_OKAY_PATH = (
    Path(CURRENT_DIR) / "outputs" / "director_agent"
    / SCENARIO_NAME / "okay_inputs" / "run_1.json"
)
CODI_PATH = (
    Path(CURRENT_DIR) / "outputs" / "codi"
    / SCENARIO_NAME / "batch" / "run_1.json"
)
EVAL_PATH = (
    Path(CURRENT_DIR) / "evaluation_results"
    / SCENARIO_NAME / "pairwise_codi_vs_director_okay.json"
)
OUTPUTS_PATH = (
    Path(CURRENT_DIR) / "evaluation_results"
    / SCENARIO_NAME / "character_outputs_okay.txt"
)

EVAL_MODEL = "gpt-4o"
DIRECTOR_MODEL = "gpt-5.5"

# Director imports (from director_agent package)

from director_core import get_director_decision
from auto_main import (
    ACTOR_SYSTEM_PROMPT,
    build_actor_prompt,
    safe_json_parse,
    validate_animation,
    should_complete_beat,
    should_close_story,
)

# Evaluation imports

from evaluation_core import (
    make_client as eval_make_client,
    transcript_to_story,
    run_ab_evaluation,
    run_single_evaluation,
    convert_ba_to_original_labels,
    aggregate_ab_ba,
)

# Phase 1 – Director generation with "okay" inputs

def run_director_okay() -> list:
    print(f"\n{'='*60}")
    print("Phase 1: Director generation (user input = 'okay' each turn)")
    print(f"{'='*60}")

    if DIRECTOR_OKAY_PATH.exists():
        print(f"  [skip] found existing: {DIRECTOR_OKAY_PATH}")
        with open(DIRECTOR_OKAY_PATH, encoding="utf-8") as f:
            return json.load(f)

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    beats = SCENARIO["beats"]
    story_topic = SCENARIO["story_topic"]

    story_state = {
        "beat_index": 0,
        "completed_beats": [],
        "story_so_far": "",
        "turns_in_current_beat": 0,
    }

    transcript = []

    for turn_idx, user_input in enumerate(OKAY_INPUTS, start=1):
        if story_state["beat_index"] >= len(beats):
            print(f"  All {len(beats)} beats complete after {turn_idx - 1} turns.")
            break

        current_beat = beats[story_state["beat_index"]]
        story_state["turns_in_current_beat"] += 1

        print(f"  Turn {turn_idx:02d} | beat={current_beat['name']} | user='{user_input}'")

        director_decision = get_director_decision(
            client=client,
            model=DIRECTOR_MODEL,
            user_input=user_input,
            story_state=story_state,
            character=OLAF_CHARACTER,
            story_topic=story_topic,
            beats=beats,
        )

        prompt = build_actor_prompt(
            user_input=user_input,
            story_state=story_state,
            director_decision=director_decision,
            character=OLAF_CHARACTER,
            story_topic=story_topic,
            beats=beats,
        )

        response = client.chat.completions.create(
            model=DIRECTOR_MODEL,
            messages=[
                {"role": "system", "content": ACTOR_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )

        raw = response.choices[0].message.content.strip()
        actor_output = safe_json_parse(
            raw,
            fallback={
                "character_response": "The story continues.",
                "story_event": "The story advances.",
                "animation": OLAF_CHARACTER["available_animations"][0],
                "beat_completed": False,
                "reason": "Actor response was not valid JSON.",
            },
        )
        actor_output["animation"] = validate_animation(
            actor_output.get("animation", ""), OLAF_CHARACTER
        )

        story_state["story_so_far"] += (
            f"\nUser: {user_input}"
            f"\nDirector Decision: {director_decision.get('decision_type')}"
            f"\nDirector Instruction: {director_decision.get('director_instruction')}"
            f"\n{OLAF_CHARACTER['name']}: {actor_output['character_response']}"
            f"\nEvent: {actor_output['story_event']}\n"
        )

        transcript.append({
            "method": "director_agent_okay_inputs",
            "character": OLAF_CHARACTER["name"],
            "scenario": SCENARIO_NAME,
            "run_id": 1,
            "turn_index": turn_idx,
            "beat": current_beat["name"],
            "user_input": user_input,
            "director_decision": director_decision,
            "actor_output": actor_output,
        })

        if should_complete_beat(actor_output, director_decision, story_state, beats):
            print(f"    -> beat '{current_beat['name']}' completed")
            story_state["completed_beats"].append(current_beat["name"])
            story_state["beat_index"] += 1
            story_state["turns_in_current_beat"] = 0

        if should_close_story(director_decision, story_state, beats):
            print(f"  Director signalled close_story.")
            break

    DIRECTOR_OKAY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DIRECTOR_OKAY_PATH, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)
    print(f"  Saved {len(transcript)} turns → {DIRECTOR_OKAY_PATH}")
    return transcript

# Phase 2 – Load CoDi output

def load_codi() -> list:
    print(f"\n{'='*60}")
    print("Phase 2: CoDi transcript")
    print(f"{'='*60}")

    if not CODI_PATH.exists():
        print(f"  ERROR: CoDi output not found at {CODI_PATH}")
        print("  Run the CoDi generation pipeline first, or run:")
        print("    python run_noderail_codi_vs_director.py --only codi")
        sys.exit(1)

    with open(CODI_PATH, encoding="utf-8") as f:
        transcript = json.load(f)

    print(f"  Loaded {len(transcript)} turns from {CODI_PATH}")
    return transcript

# Phase 3 – Pairwise evaluation

def run_eval(transcript_codi: list, transcript_director: list, model: str) -> dict:
    print(f"\n{'='*60}")
    print(f"Phase 3: Pairwise evaluation (model={model})")
    print(f"{'='*60}")

    story_codi = transcript_to_story(transcript_codi)
    story_dir  = transcript_to_story(transcript_director)

    character_profile = json.dumps(
        {
            "character": OLAF_CHARACTER,
            "story_topic": SCENARIO["story_topic"],
            "beats": SCENARIO["beats"],
        },
        indent=2,
        ensure_ascii=False,
    )

    client = eval_make_client()

    print("  Scoring CoDi (single quality)…")
    single_codi = run_single_evaluation(client, model, story_codi, character_profile)

    print("  Scoring Director (single quality)…")
    single_dir = run_single_evaluation(client, model, story_dir, character_profile)

    print("  Pairwise AB — CoDi=A, Director=B…")
    ab = run_ab_evaluation(client, model, story_codi, story_dir, character_profile)

    print("  Pairwise BA — Director=A, CoDi=B…")
    ba = run_ab_evaluation(client, model, story_dir, story_codi, character_profile)

    ba_converted = convert_ba_to_original_labels(ba["winners"])
    aggregated   = aggregate_ab_ba(ab["winners"], ba_converted)

    result = {
        "timestamp": datetime.now().isoformat(),
        "scenario": SCENARIO_NAME,
        "user_input_mode": "okay_only",
        "comparison": "codi_vs_director_okay_inputs",
        "evaluation_model": model,
        "director_model": DIRECTOR_MODEL,
        "codi_transcript_path": str(CODI_PATH),
        "director_transcript_path": str(DIRECTOR_OKAY_PATH),
        "director_turns": len(transcript_director),
        "codi_turns": len(transcript_codi),
        "single_story_scores": {
            "codi": single_codi,
            "director": single_dir,
        },
        "ab_evaluation": ab,
        "ba_evaluation": ba,
        "ba_winners_converted": ba_converted,
        "aggregated_ab_ba_winners": aggregated,
    }

    EVAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(EVAL_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\n  Saved evaluation → {EVAL_PATH}")
    return result

# Phase 4 – Extract character outputs side-by-side

def extract_character_outputs(transcript_codi: list, transcript_director: list) -> None:
    print(f"\n{'='*60}")
    print("Phase 4: Extracting character outputs")
    print(f"{'='*60}")

    lines = []

    lines.append("=== DIRECTOR_AGENT ===\n")
    for turn in transcript_director:
        turn_num  = turn.get("turn_index", "?")
        beat      = turn.get("beat", "")
        user_in   = turn.get("user_input", "okay")
        decision  = turn.get("director_decision", {})
        instr     = decision.get("director_instruction", "")
        actor_out = turn.get("actor_output", {})
        response  = actor_out.get("character_response", "").strip()

        lines.append(f"[Turn {turn_num} | Beat: {beat}]")
        lines.append(f"User:      {user_in}")
        lines.append(f"Director:  {instr}")
        lines.append(f"Character: {response}")
        lines.append("")

    lines.append("=== CODI ===\n")
    for turn in transcript_codi:
        turn_num = turn.get("turn_index", "?")
        beat     = turn.get("beat", "")
        out      = turn.get("model_output", {})
        response = out.get("character_response", "").strip()

        lines.append(f"[Turn {turn_num} | Beat: {beat}]")
        lines.append(f"Character: {response}")
        lines.append("")

    text = "\n".join(lines)

    OUTPUTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUTS_PATH, "w", encoding="utf-8") as f:
        f.write(text)

    print(f"  Director: {len(transcript_director)} turns")
    print(f"  CoDi    : {len(transcript_codi)} turns")
    print(f"  Saved → {OUTPUTS_PATH}")
    print(text)


# Summary printer

def print_summary(result: dict) -> None:
    print(f"\n{'='*60}")
    print("Summary")
    print(f"{'='*60}")

    agg = result.get("aggregated_ab_ba_winners", {})
    single = result.get("single_story_scores", {})

    print(f"\nPairwise winners (CoDi=A vs Director=B, AB+BA aggregated):")
    for dim, winner in agg.items():
        marker = "CoDi" if winner == "A" else ("Director" if winner == "B" else winner)
        print(f"  {dim:<35} → {marker}")

    codi_scores = single.get("codi", {}).get("scores", {})
    dir_scores  = single.get("director", {}).get("scores", {})

    print(f"\nIndependent quality scores:")
    print(f"  {'Dimension':<35} CoDi    Director")
    all_dims = sorted(set(list(codi_scores.keys()) + list(dir_scores.keys())))
    for dim in all_dims:
        c = codi_scores.get(dim, "-")
        d = dir_scores.get(dim, "-")
        print(f"  {dim:<35} {str(c):<8} {d}")

    print(f"\nFull results saved to:\n  {EVAL_PATH}")

# Main

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-director", action="store_true",
                        help="Skip director generation (reuse existing okay_inputs/run_1.json).")
    parser.add_argument("--skip-eval", action="store_true",
                        help="Generate transcripts only, skip evaluation.")
    parser.add_argument("--model", default=EVAL_MODEL,
                        help=f"Evaluation model (default: {EVAL_MODEL}).")
    args = parser.parse_args()

    print(f"Scenario : {SCENARIO_NAME}")
    print(f"User input: 'okay' for every Director turn")
    print(f"CoDi source: {CODI_PATH}")

    if args.skip_director and DIRECTOR_OKAY_PATH.exists():
        with open(DIRECTOR_OKAY_PATH, encoding="utf-8") as f:
            transcript_dir = json.load(f)
        print(f"[skip director] loaded {len(transcript_dir)} turns from {DIRECTOR_OKAY_PATH}")
    else:
        transcript_dir = run_director_okay()

    transcript_codi = load_codi()

    extract_character_outputs(transcript_codi, transcript_dir)

    if not args.skip_eval:
        result = run_eval(transcript_codi, transcript_dir, args.model)
        print_summary(result)
    else:
        print("\n[skip-eval] Transcripts ready. Run without --skip-eval to evaluate.")


if __name__ == "__main__":
    main()
