"""
evaluation_agent/comparison_evaluator.py

Specialized evaluator for comparing CoDi and Implementation director outputs.
Designed for robust thesis evaluation with detailed comparative analysis.

Usage:
    python -m evaluation_agent.comparison_evaluator \
        --implementation-file path/to/implementation/output.json \
        --codi-file path/to/codi/output.json \
        --character character_prompts.olaf \
        --scenario olaf_retells_red_riding_hood \
        --model gpt-4o \
        --out-dir implementation/comparison_results
"""

import os
import re
import sys
import json
import argparse
import importlib
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from typing import Dict, List, Any, Optional

from .evaluation_prompts import EVALUATE_STORY_AB_PROMPT
from .comparison_prompts import (
    COMPARE_SYSTEMS_AB_PROMPT,
    SYSTEM_EFFECTIVENESS_PROMPT,
    AGGREGATE_COMPARISON_SUMMARY_PROMPT,
    DIMENSION_SCORER_PROMPT,
    DIMENSION_RUBRICS,
)
from .evaluation_core import (
    make_client,
    load_json,
    transcript_to_story,
)

# Path setup
CURRENT_DIR = os.path.dirname(__file__)
IMPLEMENTATION_DIR = os.path.dirname(CURRENT_DIR)
sys.path.append(IMPLEMENTATION_DIR)

# Load environment
load_dotenv(os.path.join(IMPLEMENTATION_DIR, ".env"))


# ============================================================================
# Conversion utilities
# ============================================================================

def transcript_to_story_with_director(transcript: List[Dict]) -> str:
    """
    Convert transcript to story format, including director decisions.
    Shows how each system's director made decisions.
    """
    lines = []

    for i, turn in enumerate(transcript, start=1):
        beat = turn.get("beat", "unknown_beat")
        user_input = turn.get("user_input", "")
        
        # Show director decision if present
        if "director_decision" in turn and turn["director_decision"]:
            director = turn["director_decision"]
            if director.get("choice") or director.get("reasoning"):
                lines.append(f"--- TURN {i} | Beat: {beat} ---")
                lines.append(f"[DIRECTOR DECISION]")
                if director.get("reasoning"):
                    lines.append(f"Reasoning: {director['reasoning'][:200]}...")
                if director.get("choice"):
                    lines.append(f"Choice: {director['choice']}")
                if director.get("instruction"):
                    lines.append(f"Instruction: {director['instruction'][:200]}...")
                lines.append("")

        # Show user input if present
        if user_input:
            lines.append(f"User: {user_input}")

        # Show character output
        if "model_output" in turn:
            output = turn["model_output"]
            response = output.get("character_response", "")
            if response:
                lines.append(f"Character: {response}")
        elif "actor_output" in turn:
            actor_output = turn["actor_output"]
            response = actor_output.get("character_response", "")
            if response:
                lines.append(f"Character: {response}")

        lines.append("")

    return "\n".join(lines).strip()


def load_character_profile(character_module: str) -> str:
    """Load character profile from module."""
    try:
        module = importlib.import_module(character_module)
        character = module.CHARACTER
        profile = {
            "name": character["name"],
            "character_prompt": character["character_prompt"],
            "available_animations": character.get("available_animations", []),
        }
        return json.dumps(profile, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Warning: Could not load character profile: {e}")
        return "{}"


def load_scenario_context(scenario_module: str) -> Dict[str, Any]:
    """Load scenario context from module."""
    try:
        module = importlib.import_module(scenario_module)
        scenario = module.SCENARIO
        return {
            "story_topic": scenario.get("story_topic", ""),
            "beats": scenario.get("beats", []),
        }
    except Exception as e:
        print(f"Warning: Could not load scenario context: {e}")
        return {"story_topic": "", "beats": []}


def extract_codi_director_decision(direct_response: str) -> Dict[str, str]:
    """
    Extract director decision components from CoDi's direct_response field.
    
    Parses reasoning, choice (Act/Intervention/Describe/Pass), and instruction.
    """
    if not direct_response:
        return {"reasoning": "", "choice": "", "instruction": ""}
    
    decision = {
        "reasoning": "",
        "choice": "",
        "instruction": "",
    }
    
    # Extract Reason section
    reason_match = re.search(r"Reason:\s*(.+?)(?=Choice:|$)", direct_response, re.DOTALL)
    if reason_match:
        decision["reasoning"] = reason_match.group(1).strip()
    
    # Extract Choice section
    choice_match = re.search(r"Choice:\s*(.+?)(?=Instruction:|Description:|Pass|$)", direct_response, re.IGNORECASE)
    if choice_match:
        decision["choice"] = choice_match.group(1).strip()
    
    # Extract Instruction/Description
    instruction_match = re.search(
        r"(?:Instruction|Description):\s*(.+?)$", 
        direct_response, 
        re.DOTALL | re.IGNORECASE
    )
    if instruction_match:
        decision["instruction"] = instruction_match.group(1).strip()
    
    return decision


def convert_codi_output_to_transcript(codi_json_path: str) -> List[Dict[str, Any]]:
    """
    Convert CoDi JSON output to transcript format, including director decisions.
    Uses the same logic as convert_codi_to_transcript.py
    """
    data = load_json(codi_json_path)
    
    # Handle list format (CoDi outputs are often lists of examples)
    if isinstance(data, list):
        if len(data) > 0:
            data = data[0]  # Take first example
        else:
            return []
    
    # Handle wrapped data
    if "data" in data:
        data = data["data"]
    
    transcript = []
    turn_idx = 1
    
    # Extract narrative based on structure
    narrative = data.get("narrative", {})
    
    # Check for part-based structure
    if any(key.startswith("part_") for key in narrative.keys()):
        for part_key in sorted(
            [k for k in narrative.keys() if k.startswith("part_")],
            key=lambda k: int(k.split("_")[1]),
        ):
            part_data = narrative[part_key]
            for turn_key in sorted(
                [k for k in part_data.keys() if k.startswith("turn_")],
                key=lambda k: int(re.search(r"-?\d+", k).group()),
            ):
                if turn_key == "turn_-1":
                    continue
                
                turn_data = part_data.get(turn_key, {})
                story_progress = turn_data.get("story_progress", "")
                direct_response = turn_data.get("direct_response", "")
                
                if story_progress and not re.match(r"^(PART|ACT|STORY)\s+\d*\s+ENDS$", story_progress.strip(), re.IGNORECASE):
                    # Extract director decision from direct_response
                    director_decision = extract_codi_director_decision(direct_response)
                    
                    transcript.append({
                        "method": "codi",
                        "turn_index": turn_idx,
                        "beat": f"turn_{turn_idx}",
                        "user_input": "",
                        "director_decision": director_decision,
                        "model_output": {
                            "character_response": story_progress.strip(),
                            "story_event": story_progress.strip(),
                        },
                    })
                    turn_idx += 1
    else:
        # Flat structure
        for turn_key in sorted(
            [k for k in narrative.keys() if k.startswith("turn_")],
            key=lambda k: int(re.search(r"-?\d+", k).group()),
        ):
            if turn_key == "turn_-1":
                continue
            
            turn_data = narrative.get(turn_key, {})
            story_progress = turn_data.get("story_progress", "")
            direct_response = turn_data.get("direct_response", "")
            
            if story_progress and not re.match(r"^(PART|ACT|STORY)\s+\d*\s+ENDS$", story_progress.strip(), re.IGNORECASE):
                # Extract director decision from direct_response
                director_decision = extract_codi_director_decision(direct_response)
                
                transcript.append({
                    "method": "codi",
                    "turn_index": turn_idx,
                    "beat": f"turn_{turn_idx}",
                    "user_input": "",
                    "director_decision": director_decision,
                    "model_output": {
                        "character_response": story_progress.strip(),
                        "story_event": story_progress.strip(),
                    },
                })
                turn_idx += 1
    
    return transcript


# ============================================================================
# Evaluation functions
# ============================================================================

def call_evaluator(client: OpenAI, model: str, prompt: str, temperature: float = 0.0) -> str:
    """Submit evaluation prompt to LLM."""
    response = client.chat.completions.create(
        model=model,
        temperature=temperature,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert literary critic and evaluator of interactive AI character "
                    "storytelling systems. Provide detailed, nuanced analysis suitable for academic thesis evaluation."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
    )
    return response.choices[0].message.content.strip()


def parse_comparison_results(assessment: str) -> Dict[str, str]:
    """Parse comparison results from assessment text."""
    results = {}
    
    patterns = {
        "plot_structure": r"Plot\s+&\s+Structure:\s*([AB]|Comparable)",
        "narrative_control": r"Narrative\s+Control:\s*([AB]|Comparable)",
        "character_fidelity": r"Character\s+Fidelity:\s*([AB]|Comparable)",
        "language_expressiveness": r"Language\s+&\s+Expressiveness:\s*([AB]|Comparable)",
        "interactive_response": r"Interactive\s+Response:\s*([AB]|Comparable)",
        "creative_elements": r"Creative\s+Elements:\s*([AB]|Comparable)",
        "detail_thoroughness": r"Detail\s+&\s+Thoroughness:\s*([AB]|Comparable)",
        "narrative_polish": r"Narrative\s+Polish:\s*([AB]|Comparable)",
        "director_decision_making": r"Director\s+Decision-Making:\s*([AB]|Comparable)",
        "system_specific": r"System-Specific\s+Strengths:\s*([AB]|Comparable)",
        "overall": r"Overall\s+Narrative\s+Quality:\s*([AB]|Comparable)",
    }
    
    for dimension, pattern in patterns.items():
        match = re.search(pattern, assessment, re.IGNORECASE)
        if match:
            value = match.group(1).strip().upper()
            results[dimension] = value
    
    return results


def run_comparison_evaluation(
    implementation_transcript: List[Dict],
    codi_transcript: List[Dict],
    character_profile: str,
    character_name: str,
    scenario_name: str,
    client: OpenAI,
    model: str,
) -> Dict[str, Any]:
    """Run detailed comparison evaluation between the two systems."""
    
    # Convert transcripts to story format with director decisions included
    implementation_story = transcript_to_story_with_director(implementation_transcript)
    codi_story = transcript_to_story_with_director(codi_transcript)
    
    # Build comparison prompt
    comparison_prompt = COMPARE_SYSTEMS_AB_PROMPT.format(
        scenario_name=scenario_name,
        character_name=character_name,
        character_profile=character_profile,
        story_a=implementation_story,
        story_b=codi_story,
    )
    
    # Get evaluation
    assessment = call_evaluator(client, model, comparison_prompt)
    results = parse_comparison_results(assessment)
    
    return {
        "assessment": assessment,
        "comparative_scores": results,
        "implementation_story_length": len(implementation_story),
        "codi_story_length": len(codi_story),
        "implementation_turns": len(implementation_transcript),
        "codi_turns": len(codi_transcript),
    }


def run_system_effectiveness_eval(
    transcript: List[Dict],
    system_name: str,
    character_profile: str,
    character_name: str,
    scenario_name: str,
    client: OpenAI,
    model: str,
) -> Dict[str, Any]:
    """Evaluate individual system effectiveness in the scenario."""
    
    story = transcript_to_story(transcript)
    
    prompt = SYSTEM_EFFECTIVENESS_PROMPT.format(
        system_name=system_name,
        scenario_name=scenario_name,
        character_name=character_name,
        narrative=story,
        character_profile=character_profile,
    )
    
    analysis = call_evaluator(client, model, prompt)
    
    return {
        "system": system_name,
        "analysis": analysis,
        "story_length": len(story),
        "turn_count": len(transcript),
    }


# ============================================================================
# Main evaluation orchestration
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Compare CoDi and Implementation storytelling outputs"
    )
    
    parser.add_argument(
        "--implementation-file",
        required=True,
        help="Path to Implementation output JSON file",
    )
    parser.add_argument(
        "--codi-file",
        required=True,
        help="Path to CoDi output JSON file",
    )
    parser.add_argument(
        "--character",
        required=True,
        help="Character module (e.g., character_prompts.olaf)",
    )
    parser.add_argument(
        "--scenario",
        required=True,
        help="Scenario name for context",
    )
    parser.add_argument(
        "--model",
        default="gpt-4o",
        help="Evaluator model to use",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Output directory for results",
    )
    
    args = parser.parse_args()
    
    # Setup output directory
    if args.out_dir is None:
        args.out_dir = os.path.join(
            IMPLEMENTATION_DIR,
            "comparison_results",
            args.scenario,
        )
    os.makedirs(args.out_dir, exist_ok=True)
    
    # Load inputs
    print(f"Loading Implementation output from {args.implementation_file}...")
    implementation_data = load_json(args.implementation_file)
    
    # Handle both dict with "transcript" key and list format
    if isinstance(implementation_data, list):
        implementation_transcript = implementation_data
    else:
        implementation_transcript = implementation_data.get("transcript", [])
    
    print(f"Loading CoDi output from {args.codi_file}...")
    codi_transcript = convert_codi_output_to_transcript(args.codi_file)
    
    # Load character profile and scenario
    print(f"Loading character profile...")
    character_profile = load_character_profile(args.character)
    
    # Create client
    client = make_client()
    
    # Run evaluations
    print(f"Running comparison evaluation with {args.model}...")
    comparison_result = run_comparison_evaluation(
        implementation_transcript,
        codi_transcript,
        character_profile,
        args.character.split(".")[-1],
        args.scenario,
        client,
        args.model,
    )
    
    print(f"Running individual system effectiveness evaluations...")
    impl_effectiveness = run_system_effectiveness_eval(
        implementation_transcript,
        "Implementation Director Agent",
        character_profile,
        args.character.split(".")[-1],
        args.scenario,
        client,
        args.model,
    )
    
    codi_effectiveness = run_system_effectiveness_eval(
        codi_transcript,
        "CoDi Framework",
        character_profile,
        args.character.split(".")[-1],
        args.scenario,
        client,
        args.model,
    )
    
    # Compile results
    full_results = {
        "timestamp": datetime.now().isoformat(),
        "implementation_file": args.implementation_file,
        "codi_file": args.codi_file,
        "character": args.character,
        "scenario": args.scenario,
        "evaluator_model": args.model,
        "comparison_evaluation": comparison_result,
        "implementation_effectiveness": impl_effectiveness,
        "codi_effectiveness": codi_effectiveness,
    }
    
    # Save results
    output_file = os.path.join(
        args.out_dir,
        f"comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    
    print(f"Saving results to {output_file}...")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(full_results, f, indent=2, ensure_ascii=False)
    
    # Print summary
    print("\n" + "="*70)
    print("COMPARISON EVALUATION RESULTS")
    print("="*70)
    print(f"\nScenario: {args.scenario}")
    print(f"Character: {args.character}")
    print(f"\nImplementation: {comparison_result['implementation_turns']} turns, {comparison_result['implementation_story_length']} chars")
    print(f"CoDi: {comparison_result['codi_turns']} turns, {comparison_result['codi_story_length']} chars")
    print(f"\nComparative Scores:")
    for dimension, winner in comparison_result["comparative_scores"].items():
        print(f"  {dimension.upper().replace('_', ' ')}: {winner}")
    print(f"\nFull results saved to: {output_file}")
    print("="*70)


if __name__ == "__main__":
    main()
