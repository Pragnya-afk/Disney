"""
evaluation/evaluation_agent.py

Evaluation script for comparing generated story transcripts.

This module supports two evaluation settings:
    1. Pairwise comparison between two stories
    2. Independent quality scoring for each story

It is intended for comparing transcripts produced by different
story-generation pipelines, such as a baseline model and a
director-actor framework.
"""

import os
import re
import sys
import json
import argparse
import importlib
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI

from evaluation_prompts import (
    EVALUATE_STORY_AB_PROMPT,
    EVALUATE_STORY_QUALITY_PROMPT,
)


# ------------------------------------------------------------
# Path configuration
# ------------------------------------------------------------

CURRENT_DIR = os.path.dirname(__file__)
IMPLEMENTATION_DIR = os.path.dirname(CURRENT_DIR)

# Enable imports such as `character_prompts.olaf` when the script
# is executed from the project root or other locations.
sys.path.append(IMPLEMENTATION_DIR)


# ------------------------------------------------------------
# OpenAI configuration
# ------------------------------------------------------------

# Load environment variables from the project-level .env file.
load_dotenv(os.path.join(IMPLEMENTATION_DIR, ".env"))


def make_client() -> OpenAI:
    """
    Create an OpenAI client.

    Returns
    -------
    OpenAI
        Client initialized with the API key stored in the
        OPENAI_API_KEY environment variable.
    """
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ------------------------------------------------------------
# File and profile loading utilities
# ------------------------------------------------------------

def load_json(path: str):
    """
    Load a JSON file from disk.

    Parameters
    ----------
    path : str
        Path to the JSON file.

    Returns
    -------
    Any
        Parsed JSON content.
    """
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_character_profile(character_module: str) -> str:
    """
    Load character-specific evaluation context from a Python module.

    The imported module is expected to define:
        - CHARACTER

    Parameters
    ----------
    character_module : str
        Import path of the character module, e.g.
        `character_prompts.olaf`.

    Returns
    -------
    str
        JSON-formatted string containing the subset of character
        information required by the evaluator.
    """
    module = importlib.import_module(character_module)

    character = module.CHARACTER

    profile = {
        "name": character["name"],
        "character_prompt": character["character_prompt"],
        "available_animations": character["available_animations"],
    }

    return json.dumps(profile, indent=2, ensure_ascii=False)


def load_scenario_context(scenario_module: str) -> dict:
    """
    Load story context from a scenario module.

    The imported module is expected to define:
        - SCENARIO (with story_topic and beats)

    Parameters
    ----------
    scenario_module : str
        Import path of the scenario module, e.g.
        `scenarios.olaf_retells_red_riding_hood_medium`.

    Returns
    -------
    dict
        Dictionary containing story_topic and beats.
    """
    module = importlib.import_module(scenario_module)
    scenario = module.SCENARIO

    return {
        "story_topic": scenario["story_topic"],
        "beats": scenario["beats"],
    }


# ------------------------------------------------------------
# Transcript conversion
# ------------------------------------------------------------

def transcript_to_story(transcript: list) -> str:
    """
    Convert a transcript JSON structure into a readable textual story.

    The evaluator model operates on a textual representation rather
    than raw structured JSON. This function therefore serializes each
    turn into a consistent, human-readable format.

    Supported transcript structures
    -------------------------------
    1. Baseline format:
       Each turn contains `model_output`.

    2. Director-agent format:
       Each turn contains `actor_output` and may also include
       `director_decision`.

    Parameters
    ----------
    transcript : list
        List of transcript turns.

    Returns
    -------
    str
        Flattened story-like text used as input to the evaluator.
    """
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


# ------------------------------------------------------------
# Evaluator model call
# ------------------------------------------------------------

def call_evaluator(client: OpenAI, model: str, prompt: str) -> str:
    """
    Submit an evaluation prompt to the language model.

    A deterministic setting is used to improve reproducibility
    across evaluation runs.

    Parameters
    ----------
    client : OpenAI
        OpenAI client instance.
    model : str
        Model name to use for evaluation.
    prompt : str
        Fully formatted user prompt.

    Returns
    -------
    str
        Raw textual evaluation produced by the model.
    """
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


# ------------------------------------------------------------
# Output parsing utilities
# ------------------------------------------------------------

def parse_ab_winners(assessment: str) -> dict:
    """
    Parse categorical winners from a pairwise A/B assessment.

    The expected response format includes entries such as:
        Plot: A
        Development: B
        Overall: Same

    Parameters
    ----------
    assessment : str
        Raw evaluator response.

    Returns
    -------
    dict
        Mapping from evaluation dimension to one of:
        {"A", "B", "Same", "ParseError"}.
    """
    dimensions = [
        "Plot",
        "Development",
        "Language Use",
        "Interruption Handling",
        "Character Fidelity",
        "Narrative Control",
        "Overall",
    ]

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


def parse_single_scores(assessment: str) -> dict:
    """
    Parse numerical quality scores from a single-story assessment.

    The expected response format includes entries such as:
        Plot: 8 / 10
        Character Fidelity: 9.5 / 10

    Parameters
    ----------
    assessment : str
        Raw evaluator response.

    Returns
    -------
    dict
        Mapping from evaluation dimension to a float score.
        Missing dimensions are assigned None.
    """
    dimensions = [
        "Plot",
        "Development",
        "Language Use",
        "Interruption Handling",
        "Character Fidelity",
        "Narrative Control",
        "Overall",
    ]

    scores = {}

    for dim in dimensions:
        pattern = rf"{re.escape(dim)}:\s*([0-9]+(?:\.[0-9]+)?)\s*/\s*10"
        match = re.search(pattern, assessment, re.IGNORECASE)

        if match:
            scores[dim] = float(match.group(1))
        else:
            scores[dim] = None

    return scores


# ------------------------------------------------------------
# Evaluation procedures
# ------------------------------------------------------------

def run_ab_evaluation(
    client: OpenAI,
    model: str,
    story_a: str,
    story_b: str,
    character_profile: str,
) -> dict:
    """
    Run a pairwise A/B evaluation.

    Parameters
    ----------
    client : OpenAI
        OpenAI client instance.
    model : str
        Model name.
    story_a : str
        Textual representation of story A.
    story_b : str
        Textual representation of story B.
    character_profile : str
        JSON-formatted character and story context.

    Returns
    -------
    dict
        Dictionary containing the full assessment text and the
        parsed winners by evaluation dimension.
    """
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
    """
    Run an independent quality evaluation for a single story.

    Parameters
    ----------
    client : OpenAI
        OpenAI client instance.
    model : str
        Model name.
    story : str
        Textual representation of the story.
    character_profile : str
        JSON-formatted character and story context.

    Returns
    -------
    dict
        Dictionary containing the full assessment text and the
        parsed numerical scores.
    """
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


# ------------------------------------------------------------
# AB/BA aggregation
# ------------------------------------------------------------

def convert_ba_to_original_labels(ba_winners: dict) -> dict:
    """
    Convert BA evaluation labels back to the original A/B reference frame.

    In the BA setting, the original story order is reversed:
        BA.A corresponds to original B
        BA.B corresponds to original A

    Parameters
    ----------
    ba_winners : dict
        Winners parsed from the BA evaluation.

    Returns
    -------
    dict
        Winners expressed again in terms of the original A/B labels.
    """
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
    """
    Aggregate AB and BA results to mitigate order effects.

    A dimension is assigned a winner only if both orderings
    agree after BA is converted back into the original label space.
    Otherwise, the result is marked as "Same".

    Parameters
    ----------
    ab_winners : dict
        Winners from the AB evaluation.
    ba_winners_converted : dict
        BA winners converted to the original label space.

    Returns
    -------
    dict
        Aggregated winner labels by dimension.
    """
    aggregated = {}

    for dim in ab_winners:
        ab = ab_winners.get(dim)
        ba = ba_winners_converted.get(dim)

        if ab == ba:
            aggregated[dim] = ab
        else:
            aggregated[dim] = "Same"

    return aggregated


# ------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------

def main():
    """
    Execute the transcript evaluation pipeline.

    Workflow
    --------
    1. Parse command-line arguments
    2. Load transcripts and character profile
    3. Convert transcripts into evaluator-readable stories
    4. Run single-story evaluation for both stories
    5. Run pairwise A/B evaluation
    6. Optionally run reversed B/A evaluation and aggregate results
    7. Save all outputs to disk
    8. Print a concise summary to the terminal
    """
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
        default="evaluation/results",
        help="Directory to save evaluation results.",
    )

    parser.add_argument(
        "--model",
        default="gpt-4o",
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

        ba_winners_converted = convert_ba_to_original_labels(
            ba_result["winners"]
        )

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