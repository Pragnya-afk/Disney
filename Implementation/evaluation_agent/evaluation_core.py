"""
evaluation_agent/evaluation_core.py

Evaluation engine for comparing generated story transcripts.

Supports three evaluation contexts:
    BASE  — baseline vs director_agent
    CODI  — director_agent vs CoDi
    TIME  — time-constrained run comparisons

Each context runs two evaluation modes:
    1. Pairwise A/B comparison with AB/BA order-bias mitigation
    2. Independent quality scoring per story

CoDi-specific utilities (transcript conversion, comparison runners)
are also housed here after merging from comparison_evaluator.py.
"""

import os
import re
import sys
import json
import argparse
import importlib
from datetime import datetime
from typing import Dict, List, Any
from dotenv import load_dotenv
from openai import OpenAI

try:
    from .evaluation_prompts import (
        BASE_DIMENSIONS,
        CODI_DIMENSIONS,
        TIME_DIMENSIONS,
        ADVERSARIAL_DIMENSIONS,
        EVALUATE_STORY_AB_PROMPT,
        EVALUATE_STORY_QUALITY_PROMPT,
        EVALUATE_CODI_AB_PROMPT,
        EVALUATE_CODI_QUALITY_PROMPT,
        EVALUATE_TIME_AB_PROMPT,
        EVALUATE_TIME_QUALITY_PROMPT,
        EVALUATE_ADVERSARIAL_AB_PROMPT,
        EVALUATE_ADVERSARIAL_QUALITY_PROMPT,
    )
except ImportError:
    from evaluation_prompts import (
        BASE_DIMENSIONS,
        CODI_DIMENSIONS,
        TIME_DIMENSIONS,
        ADVERSARIAL_DIMENSIONS,
        EVALUATE_STORY_AB_PROMPT,
        EVALUATE_STORY_QUALITY_PROMPT,
        EVALUATE_CODI_AB_PROMPT,
        EVALUATE_CODI_QUALITY_PROMPT,
        EVALUATE_TIME_AB_PROMPT,
        EVALUATE_TIME_QUALITY_PROMPT,
        EVALUATE_ADVERSARIAL_AB_PROMPT,
        EVALUATE_ADVERSARIAL_QUALITY_PROMPT,
    )


# Path configuration

CURRENT_DIR = os.path.dirname(__file__)
IMPLEMENTATION_DIR = os.path.dirname(CURRENT_DIR)

# Enable imports such as `character_prompts.olaf` when the script
# is executed from the project root or other locations.
sys.path.append(IMPLEMENTATION_DIR)

from config import EVALUATION_CORE_CLI_MODEL  # noqa: E402

# OpenAI configuration

# Load environment variables from the project-level .env file.
load_dotenv(os.path.join(IMPLEMENTATION_DIR, ".env"))


def make_client() -> OpenAI:
    """Create an OpenAI client from OPENAI_API_KEY."""
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# File and profile loading utilities


def load_json(path: str):
    """Load a JSON file from disk."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_character_profile(character_module: str) -> str:
    """Return the character profile (name, prompt, animations) as a JSON string."""
    module = importlib.import_module(character_module)

    character = module.CHARACTER

    profile = {
        "name": character["name"],
        "character_prompt": character["character_prompt"],
        "available_animations": character["available_animations"],
    }

    return json.dumps(profile, indent=2, ensure_ascii=False)


def load_scenario_context(scenario_module: str) -> dict:
    """Return story topic and beats from a scenario module."""
    module = importlib.import_module(scenario_module)
    scenario = module.SCENARIO

    return {
        "story_topic": scenario["story_topic"],
        "beats": scenario["beats"],
    }


# Transcript conversion


def transcript_to_story(transcript: list) -> str:
    """Render a baseline or director transcript as readable story text for the judge."""
    lines = []

    for i, turn in enumerate(transcript, start=1):
        beat = turn.get("beat", "unknown_beat")
        user_input = turn.get("user_input", "")

        lines.append(f"Turn {i} | Beat: {beat}")
        lines.append(f"User: {user_input}")

        # Baseline transcript format
        if "model_output" in turn:
            output = turn["model_output"]
            response = output.get("character_response", "")
            event = output.get("story_event", "")
            animation = output.get("animation", "")
            beat_completed = output.get("beat_completed", False)

            lines.append(f"Character: {response}")
            lines.append(f"Story Event: {event}")
            lines.append(f"Animation: {animation}")
            lines.append(f"Beat Completed: {beat_completed}")

        # Director-agent transcript format
        elif "actor_output" in turn:
            director_decision = turn.get("director_decision", {})
            actor_output = turn.get("actor_output", {})

            decision_type = director_decision.get("decision_type", "")
            interruption = director_decision.get("interruption_detected", "")
            instruction = director_decision.get("director_instruction", "")

            response = actor_output.get("character_response", "")
            event = actor_output.get("story_event", "")
            animation = actor_output.get("animation", "")
            beat_completed = actor_output.get("beat_completed", False)

            lines.append(f"Director Decision: {decision_type}")
            lines.append(f"Interruption Detected: {interruption}")
            lines.append(f"Director Instruction: {instruction}")
            lines.append(f"Character: {response}")
            lines.append(f"Story Event: {event}")
            lines.append(f"Animation: {animation}")
            lines.append(f"Beat Completed: {beat_completed}")

        # Fallback for unsupported or unforeseen transcript structures
        else:
            lines.append(f"Raw Turn: {json.dumps(turn, ensure_ascii=False)}")

        lines.append("")

    return "\n".join(lines).strip()


# Evaluator model call


def call_evaluator(client: OpenAI, model: str, prompt: str) -> str:
    """Send one judge prompt to the evaluator model at temperature 0."""
    response = client.chat.completions.create(
        model=model,
        temperature=0.0,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a careful literary critic and evaluator of "
                    "interactive AI character stories."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
    )

    return response.choices[0].message.content.strip()


# Output parsing utilities


def parse_ab_winners(assessment: str, dimensions: list = None) -> dict:
    """Parse 'Dimension: A|B|Same' lines; missing dimensions become ParseError."""
    if dimensions is None:
        dimensions = BASE_DIMENSIONS

    winners = {}

    for dim in dimensions:
        pattern = rf"{re.escape(dim)}:\s*(A|B|Same)"
        match = re.search(pattern, assessment, re.IGNORECASE)

        if match:
            value = match.group(1)
            winners[dim] = "Same" if value.lower() == "same" else value.upper()
        else:
            winners[dim] = "ParseError"

    return winners


def parse_single_scores(assessment: str, dimensions: list = None) -> dict:
    """Parse 'Dimension: x / 10' lines; missing dimensions become None."""
    if dimensions is None:
        dimensions = BASE_DIMENSIONS

    scores = {}

    for dim in dimensions:
        pattern = rf"{re.escape(dim)}:\s*([0-9]+(?:\.[0-9]+)?)\s*/\s*10"
        match = re.search(pattern, assessment, re.IGNORECASE)

        if match:
            scores[dim] = float(match.group(1))
        else:
            scores[dim] = None

    return scores


# Evaluation procedures


def run_ab_evaluation(
    client: OpenAI,
    model: str,
    story_a: str,
    story_b: str,
    character_profile: str,
) -> dict:
    """Run one pairwise A/B judge call and parse the winners."""
    prompt = EVALUATE_STORY_AB_PROMPT.format(
        character_profile=character_profile,
        story_a=story_a,
        story_b=story_b,
    )

    assessment = call_evaluator(client, model, prompt)
    winners = parse_ab_winners(assessment)

    return {
        "assessment": assessment,
        "winners": winners,
    }


def run_single_evaluation(
    client: OpenAI,
    model: str,
    story: str,
    character_profile: str,
) -> dict:
    """Run one single-story judge call and parse the scores."""
    prompt = EVALUATE_STORY_QUALITY_PROMPT.format(
        character_profile=character_profile,
        story=story,
    )

    assessment = call_evaluator(client, model, prompt)
    scores = parse_single_scores(assessment)

    return {
        "assessment": assessment,
        "scores": scores,
    }


# AB/BA aggregation


def convert_ba_to_original_labels(ba_winners: dict) -> dict:
    """Map winners from the swapped (BA) run back to the original A/B labels."""
    converted = {}

    for dim, winner in ba_winners.items():
        if winner == "A":
            converted[dim] = "B"
        elif winner == "B":
            converted[dim] = "A"
        else:
            converted[dim] = winner

    return converted


def aggregate_ab_ba(ab_winners: dict, ba_winners_converted: dict) -> dict:
    """Combine AB and BA verdicts per dimension to cancel position bias."""
    aggregated = {}

    for dim in ab_winners:
        ab = ab_winners.get(dim)
        ba = ba_winners_converted.get(dim)

        if ab == ba:
            aggregated[dim] = ab
        else:
            aggregated[dim] = "Same"

    return aggregated


# CoDi transcript conversion


def extract_codi_director_decision(direct_response: str) -> Dict[str, str]:
    """
    Parse reasoning, choice, and instruction from a CoDi direct_response field.
    """
    if not direct_response:
        return {"reasoning": "", "choice": "", "instruction": ""}

    decision = {"reasoning": "", "choice": "", "instruction": ""}

    reason_match = re.search(r"Reason:\s*(.+?)(?=Choice:|$)", direct_response, re.DOTALL)
    if reason_match:
        decision["reasoning"] = reason_match.group(1).strip()

    choice_match = re.search(
        r"Choice:\s*(.+?)(?=Instruction:|Description:|Pass|$)",
        direct_response,
        re.IGNORECASE,
    )
    if choice_match:
        decision["choice"] = choice_match.group(1).strip()

    instruction_match = re.search(
        r"(?:Instruction|Description):\s*(.+?)$",
        direct_response,
        re.DOTALL | re.IGNORECASE,
    )
    if instruction_match:
        decision["instruction"] = instruction_match.group(1).strip()

    return decision


def convert_codi_output_to_transcript(codi_json_path: str) -> List[Dict[str, Any]]:
    """Convert a CoDi JSON output file to the standard transcript format."""
    data = load_json(codi_json_path)

    if isinstance(data, list):
        data = data[0] if data else {}
    if "data" in data:
        data = data["data"]

    transcript = []
    turn_idx = 1
    narrative = data.get("narrative", {})

    def _process_turn(turn_data: dict):
        nonlocal turn_idx
        story_progress = turn_data.get("story_progress", "")
        direct_response = turn_data.get("direct_response", "")

        if story_progress and not re.match(
            r"^(PART|ACT|STORY)\s+\d*\s+ENDS$", story_progress.strip(), re.IGNORECASE
        ):
            transcript.append(
                {
                    "method": "codi",
                    "turn_index": turn_idx,
                    "beat": f"turn_{turn_idx}",
                    "user_input": "",
                    "director_decision": extract_codi_director_decision(direct_response),
                    "model_output": {
                        "character_response": story_progress.strip(),
                        "story_event": story_progress.strip(),
                    },
                }
            )
            turn_idx += 1

    if any(k.startswith("part_") for k in narrative):
        for part_key in sorted(
            (k for k in narrative if k.startswith("part_")),
            key=lambda k: int(k.split("_")[1]),
        ):
            part_data = narrative[part_key]
            for turn_key in sorted(
                (k for k in part_data if k.startswith("turn_")),
                key=lambda k: int(re.search(r"-?\d+", k).group()),
            ):
                if turn_key != "turn_-1":
                    _process_turn(part_data[turn_key])
    else:
        for turn_key in sorted(
            (k for k in narrative if k.startswith("turn_")),
            key=lambda k: int(re.search(r"-?\d+", k).group()),
        ):
            if turn_key != "turn_-1":
                _process_turn(narrative[turn_key])

    return transcript


def transcript_to_story_with_director(transcript: List[Dict]) -> str:
    """
    Convert a transcript to story text, including director reasoning and choices.
    """
    lines = []

    for i, turn in enumerate(transcript, start=1):
        beat = turn.get("beat", "unknown_beat")
        user_input = turn.get("user_input", "")

        director = turn.get("director_decision", {})
        if director and (director.get("choice") or director.get("reasoning")):
            lines.append(f"--- TURN {i} | Beat: {beat} ---")
            lines.append("[DIRECTOR DECISION]")
            if director.get("reasoning"):
                lines.append(f"Reasoning: {director['reasoning'][:200]}...")
            if director.get("choice"):
                lines.append(f"Choice: {director['choice']}")
            if director.get("instruction"):
                lines.append(f"Instruction: {director['instruction'][:200]}...")
            lines.append("")

        if user_input:
            lines.append(f"User: {user_input}")

        if "model_output" in turn:
            response = turn["model_output"].get("character_response", "")
        elif "actor_output" in turn:
            response = turn["actor_output"].get("character_response", "")
        else:
            response = ""

        if response:
            lines.append(f"Character: {response}")

        lines.append("")

    return "\n".join(lines).strip()


# CoDi evaluation runners


def run_codi_comparison(
    client: OpenAI,
    model: str,
    implementation_transcript: List[Dict],
    codi_transcript: List[Dict],
    character_profile: str,
    character_name: str,
    scenario_name: str,
) -> Dict[str, Any]:
    """Pairwise A/B judge call: Implementation director vs. CoDi."""
    implementation_story = transcript_to_story_with_director(implementation_transcript)
    codi_story = transcript_to_story_with_director(codi_transcript)

    prompt = EVALUATE_CODI_AB_PROMPT.format(
        scenario_name=scenario_name,
        character_name=character_name,
        character_profile=character_profile,
        story_a=implementation_story,
        story_b=codi_story,
    )

    assessment = call_evaluator(client, model, prompt)
    winners = parse_ab_winners(assessment, CODI_DIMENSIONS)

    return {
        "assessment": assessment,
        "winners": winners,
        "implementation_turns": len(implementation_transcript),
        "codi_turns": len(codi_transcript),
        "implementation_story_length": len(implementation_story),
        "codi_story_length": len(codi_story),
    }


def run_codi_quality_eval(
    client: OpenAI,
    model: str,
    transcript: List[Dict],
    system_name: str,
    character_profile: str,
    character_name: str,
    scenario_name: str,
) -> Dict[str, Any]:
    """Single-story judge call for a CoDi or Implementation story."""
    story = transcript_to_story(transcript)

    prompt = EVALUATE_CODI_QUALITY_PROMPT.format(
        system_name=system_name,
        scenario_name=scenario_name,
        character_name=character_name,
        character_profile=character_profile,
        story=story,
    )

    assessment = call_evaluator(client, model, prompt)
    scores = parse_single_scores(assessment, CODI_DIMENSIONS)

    return {
        "system": system_name,
        "assessment": assessment,
        "scores": scores,
        "story_length": len(story),
        "turn_count": len(transcript),
    }


# Adversarial evaluation runners


def run_adversarial_comparison(
    client: OpenAI,
    model: str,
    transcript_a: List[Dict],
    transcript_b: List[Dict],
    character_profile: str,
    character_name: str,
    scenario_name: str,
    derailment_category: str,
) -> Dict[str, Any]:
    """Pairwise A/B judge call focused on adversarial robustness."""
    story_a = transcript_to_story_with_director(transcript_a)
    story_b = transcript_to_story_with_director(transcript_b)

    prompt = EVALUATE_ADVERSARIAL_AB_PROMPT.format(
        derailment_category=derailment_category,
        scenario_name=scenario_name,
        character_name=character_name,
        character_profile=character_profile,
        story_a=story_a,
        story_b=story_b,
        adversarial_jailbreak="prompt injection, identity denial, override commands",
        targeted_goal="coordinated sustained pressure to stop the story, including direct instructions to the director layer",
    )

    assessment = call_evaluator(client, model, prompt)
    winners = parse_ab_winners(assessment, ADVERSARIAL_DIMENSIONS)

    return {
        "assessment": assessment,
        "winners": winners,
        "derailment_category": derailment_category,
        "turns_a": len(transcript_a),
        "turns_b": len(transcript_b),
    }


def run_adversarial_quality_eval(
    client: OpenAI,
    model: str,
    transcript: List[Dict],
    system_name: str,
    character_profile: str,
    character_name: str,
    scenario_name: str,
    derailment_category: str,
) -> Dict[str, Any]:
    """Single-story robustness judge call for an adversarial transcript."""
    story = transcript_to_story_with_director(transcript)

    prompt = EVALUATE_ADVERSARIAL_QUALITY_PROMPT.format(
        system_name=system_name,
        derailment_category=derailment_category,
        scenario_name=scenario_name,
        character_name=character_name,
        character_profile=character_profile,
        story=story,
    )

    assessment = call_evaluator(client, model, prompt)
    scores = parse_single_scores(assessment, ADVERSARIAL_DIMENSIONS)

    return {
        "system": system_name,
        "assessment": assessment,
        "scores": scores,
        "derailment_category": derailment_category,
        "story_length": len(story),
        "turn_count": len(transcript),
    }


# Main entry point


def main():
    """CLI: evaluate one pair of transcripts (AB + BA + single-story scores)."""
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--story-a",
        required=True,
        help="Path to first transcript JSON file.",
    )

    parser.add_argument(
        "--story-b",
        required=True,
        help="Path to second transcript JSON file.",
    )

    parser.add_argument(
        "--character-module",
        required=True,
        help="Character module, e.g. character_prompts.olaf",
    )

    parser.add_argument(
        "--scenario-module",
        required=True,
        help="Scenario module, e.g. scenarios.olaf_retells_red_riding_hood_medium",
    )

    parser.add_argument(
        "--out-dir",
        default=os.path.join(IMPLEMENTATION_DIR, "evaluation_results"),
        help="Directory to save evaluation results.",
    )

    parser.add_argument(
        "--model",
        default=EVALUATION_CORE_CLI_MODEL,
        help="Evaluator model.",
    )

    parser.add_argument(
        "--ab-ba",
        action="store_true",
        help="Run both AB and BA orderings to reduce order bias.",
    )

    args = parser.parse_args()

    client = make_client()
    os.makedirs(args.out_dir, exist_ok=True)

    transcript_a = load_json(args.story_a)
    transcript_b = load_json(args.story_b)

    character_profile_data = json.loads(load_character_profile(args.character_module))
    scenario_context = load_scenario_context(args.scenario_module)

    # Combine character profile with scenario context
    character_profile_data.update(scenario_context)
    character_profile = json.dumps(character_profile_data, indent=2, ensure_ascii=False)

    story_a = transcript_to_story(transcript_a)
    story_b = transcript_to_story(transcript_b)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Independent scoring of each story
    single_a = run_single_evaluation(
        client=client,
        model=args.model,
        story=story_a,
        character_profile=character_profile,
    )

    single_b = run_single_evaluation(
        client=client,
        model=args.model,
        story=story_b,
        character_profile=character_profile,
    )

    # Direct A/B comparison
    ab_result = run_ab_evaluation(
        client=client,
        model=args.model,
        story_a=story_a,
        story_b=story_b,
        character_profile=character_profile,
    )

    result = {
        "story_a_path": args.story_a,
        "story_b_path": args.story_b,
        "character_module": args.character_module,
        "model": args.model,
        "ab_ba_enabled": args.ab_ba,
        "single_story_scores": {
            "A": single_a,
            "B": single_b,
        },
        "ab_evaluation": ab_result,
    }

    # Reversed comparison for order-bias mitigation
    if args.ab_ba:
        ba_result = run_ab_evaluation(
            client=client,
            model=args.model,
            story_a=story_b,
            story_b=story_a,
            character_profile=character_profile,
        )

        ba_winners_converted = convert_ba_to_original_labels(ba_result["winners"])

        aggregated = aggregate_ab_ba(
            ab_result["winners"],
            ba_winners_converted,
        )

        result["ba_evaluation"] = ba_result
        result["ba_winners_converted_to_original_labels"] = ba_winners_converted
        result["aggregated_ab_ba_winners"] = aggregated

    output_path = os.path.join(
        args.out_dir,
        f"evaluation_result_{timestamp}.json",
    )

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print("\nEvaluation complete.")
    print(f"Saved result to: {output_path}")

    print("\nAB winners:")
    for dim, winner in ab_result["winners"].items():
        print(f"{dim}: {winner}")

    if args.ab_ba:
        print("\nAggregated AB/BA winners:")
        for dim, winner in result["aggregated_ab_ba_winners"].items():
            print(f"{dim}: {winner}")


if __name__ == "__main__":
    main()
