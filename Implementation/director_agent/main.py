"""
director_agent/main.py

Interactive director-agent implementation.

Example:
    python director_agent/main.py \
      --character character_prompts.olaf \
      --scenario scenarios.olaf_retells_red_riding_hood_derail
"""

import os
import sys
import json
import argparse
from dotenv import load_dotenv
from openai import OpenAI

CURRENT_DIR = os.path.dirname(__file__)
IMPLEMENTATION_DIR = os.path.dirname(CURRENT_DIR)
sys.path.append(IMPLEMENTATION_DIR)

from director_core import get_director_decision
from director_agent.actor_common import (
    ACTOR_SYSTEM_PROMPT,
    build_actor_prompt,
    load_module,
    should_complete_beat,
    validate_animation,
)

load_dotenv(os.path.join(IMPLEMENTATION_DIR, ".env"))

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
from config import INTERACTIVE_MODEL

MODEL = INTERACTIVE_MODEL


def safe_json_parse(raw: str, fallback: dict) -> dict:
    """Parse model JSON, returning the fallback unchanged on failure."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return fallback


def call_actor_agent(
    user_input: str,
    story_state: dict,
    director_decision: dict,
    character: dict,
    story_topic: str,
    beats: list,
) -> dict:
    """Call the actor LLM for one turn and return its parsed JSON output."""
    prompt = build_actor_prompt(
        user_input=user_input,
        story_state=story_state,
        director_decision=director_decision,
        character=character,
        story_topic=story_topic,
        beats=beats,
    )

    response = client.chat.completions.create(
        model=MODEL,
        temperature=0.45,
        messages=[
            {"role": "system", "content": ACTOR_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )

    raw = response.choices[0].message.content.strip()

    fallback = {
        "character_response": "The story moves forward into a new moment.",
        "story_event": "The story advances with a new moment.",
        "animation": character["available_animations"][0],
        "beat_completed": False,
        "reason": "Actor response was not valid JSON.",
        "raw_model_response": raw,
    }

    return safe_json_parse(raw, fallback)


def should_close_story(director_decision: dict) -> bool:
    """True if the director decided to close the story."""
    return director_decision.get("decision_type") == "close_story"


def run(character_module: str, scenario_module: str) -> None:
    """Interactive terminal loop: director + actor respond to typed user input."""
    character_mod = load_module(character_module)
    scenario_mod = load_module(scenario_module)

    character = character_mod.CHARACTER
    scenario = scenario_mod.SCENARIO

    story_topic = scenario["story_topic"]
    beats = scenario["beats"]

    story_state = {
        "beat_index": 0,
        "completed_beats": [],
        "story_so_far": "",
        "turns_in_current_beat": 0,
    }

    scenario_folder = scenario_module.split(".")[-1]
    output_dir = os.path.join(
        IMPLEMENTATION_DIR,
        "outputs",
        "director_agent",
        scenario_folder,
        "interactive",
    )
    os.makedirs(output_dir, exist_ok=True)
    transcript = []

    print("\nDirector-agent storytelling started.")
    print(f"Loaded character: {character['name']}")
    print(f"Loaded scenario: {scenario['scenario_name']}")
    print("Type your message. Type 'quit' to stop.\n")

    # Each turn, get user input, call director agent for decision, call actor agent for response, update story state, and repeat until story ends or user quits.
    while story_state["beat_index"] < len(beats):
        current_beat = beats[story_state["beat_index"]]

        print(f"\nCurrent beat: {current_beat['name']}")

        # Currently user input first before character introduces themself
        user_input = input("You: ")

        if user_input.lower().strip() in ["quit", "exit", "stop"]:
            break

        story_state["turns_in_current_beat"] += 1

        director_decision = get_director_decision(
            client=client,
            model=MODEL,
            user_input=user_input,
            story_state=story_state,
            character=character,
            story_topic=story_topic,
            beats=beats,
        )
        # Actor agent call and response handling ie recieves director decision and produces character response, story event, animation, and beat completion status. Also updates story state and transcript.
        actor_output = call_actor_agent(
            user_input=user_input,
            story_state=story_state,
            director_decision=director_decision,
            character=character,
            story_topic=story_topic,
            beats=beats,
        )

        actor_output["animation"] = validate_animation(actor_output.get("animation", ""), character)

        print(f"\nDirector decision: {director_decision.get('decision_type')}")
        print(f"{character['name']}: {actor_output['character_response']}")
        print(f"[Animation: {actor_output['animation']}]")

        story_state["story_so_far"] += (
            f"\nUser: {user_input}"
            f"\nDirector Decision: {director_decision.get('decision_type')}"
            f"\nDirector Instruction: {director_decision.get('director_instruction')}"
            f"\n{character['name']}: {actor_output['character_response']}"
            f"\nEvent: {actor_output['story_event']}\n"
        )

        transcript.append(
            {
                "method": "director_agent",
                "character": character["name"],
                "scenario": scenario["scenario_name"],
                "beat": current_beat["name"],
                "user_input": user_input,
                "director_decision": director_decision,
                "actor_output": actor_output,
            }
        )

        if should_complete_beat(actor_output, director_decision, story_state, beats):
            story_state["completed_beats"].append(current_beat["name"])
            story_state["beat_index"] += 1
            story_state["turns_in_current_beat"] = 0

        if should_close_story(director_decision):
            break

    transcript_path = os.path.join(output_dir, "interactive.json")

    with open(transcript_path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)

    print("\nStory finished or stopped.")
    print(f"Saved transcript to {transcript_path}")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", required=True, help="e.g. character_prompts.olaf")
    parser.add_argument(
        "--scenario", required=True, help="e.g. scenarios.olaf_retells_red_riding_hood_derail"
    )
    args = parser.parse_args()

    run(args.character, args.scenario)


if __name__ == "__main__":
    main()
