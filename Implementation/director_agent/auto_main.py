"""
director_agent/auto_main.py

Non-interactive director-agent story run.

Example:
    python director_agent/auto_main.py \
      --character character_prompts.olaf \
      --scenario scenarios.olaf_retells_red_riding_hood_derail \
      --run-id 1
"""

import os
import sys
import json
import argparse
from dotenv import load_dotenv

CURRENT_DIR = os.path.dirname(__file__)
IMPLEMENTATION_DIR = os.path.dirname(CURRENT_DIR)
sys.path.append(IMPLEMENTATION_DIR)

from director_core import get_director_decision
from director_agent.actor_common import (
    ACTOR_SYSTEM_PROMPT,
    build_actor_prompt,
    load_module,
    load_scenario,
    make_client,
    safe_json_parse,
    should_complete_beat,
    validate_animation,
)

load_dotenv(os.path.join(IMPLEMENTATION_DIR, ".env"))


from config import DIRECTOR_BATCH_MODEL

MODEL = DIRECTOR_BATCH_MODEL


def should_close_story(director_decision: dict, story_state: dict, beats: list) -> bool:
    # Only honour close_story when all beats are genuinely done.
    # This guards against the director misclassifying a story-stop attempt
    # as a legitimate end-of-story signal.
    if director_decision.get("decision_type") != "close_story":
        return False
    return story_state["beat_index"] >= len(beats) - 1


def run_story(character_module: str, scenario_module: str, run_id: int, scenario_name_override: str | None = None) -> str:
    client = make_client()

    character_mod = load_module(character_module)
    character = character_mod.CHARACTER
    scenario = load_scenario(scenario_module, scenario_name_override)

    story_topic = scenario["story_topic"]
    beats = scenario["beats"]
    user_inputs = scenario["user_inputs"]
    scenario_name = scenario["scenario_name"]
    scenario_folder = scenario_name

    story_state = {
        "beat_index": 0,
        "completed_beats": [],
        "story_so_far": "",
        "turns_in_current_beat": 0,
    }

    output_dir = os.path.join(
        IMPLEMENTATION_DIR,
        "outputs",
        "director_agent",
        scenario_folder,
        "batch",
    )
    os.makedirs(output_dir, exist_ok=True)

    transcript = []

    for turn_idx, user_input in enumerate(user_inputs, start=1):
        if story_state["beat_index"] >= len(beats):
            break

        current_beat = beats[story_state["beat_index"]]
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
            messages=[
                {"role": "system", "content": ACTOR_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )

        raw = response.choices[0].message.content.strip()

        actor_output = safe_json_parse(
            raw,
            fallback={
                "character_response": "The story moves forward into a new moment.",
                "story_event": "The story advances with a new moment.",
                "animation": character["available_animations"][0],
                "beat_completed": False,
                "reason": "Actor response was not valid JSON.",
            },
        )

        actor_output["animation"] = validate_animation(
            actor_output.get("animation", ""), character
        )

        story_state["story_so_far"] += (
            f"\nUser: {user_input}"
            f"\nDirector Decision: {director_decision.get('decision_type')}"
            f"\nDirector Instruction: {director_decision.get('director_instruction')}"
            f"\n{character['name']}: {actor_output['character_response']}"
            f"\nEvent: {actor_output['story_event']}\n"
        )

        transcript.append({
            "method": "director_agent",
            "character": character["name"],
            "scenario": scenario_name,
            "run_id": run_id,
            "turn_index": turn_idx,
            "beat": current_beat["name"],
            "user_input": user_input,
            "director_decision": director_decision,
            "actor_output": actor_output,
        })

        if should_complete_beat(actor_output, director_decision, story_state, beats):
            story_state["completed_beats"].append(current_beat["name"])
            story_state["beat_index"] += 1
            story_state["turns_in_current_beat"] = 0

        if should_close_story(director_decision, story_state, beats):
            break

    transcript_path = os.path.join(output_dir, f"run_{run_id}.json")

    with open(transcript_path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)

    print(f"[director_agent] saved: {transcript_path}")
    return transcript_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", required=True, help="e.g. character_prompts.olaf")
    parser.add_argument("--scenario", required=True, help="e.g. scenarios.olaf_derailment_scenario_suite")
    parser.add_argument("--scenario-name", default=None, help="For suite modules: e.g. olaf_retells_red_riding_hood_no_derailment")
    parser.add_argument("--run-id", type=int, default=1)
    args = parser.parse_args()

    run_story(args.character, args.scenario, args.run_id, args.scenario_name)


if __name__ == "__main__":
    main()