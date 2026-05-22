"""
director_agent/time_strict_auto_main.py

Strict wall-clock time-constrained director-agent story run.

Example:
    python director_agent/time_strict_auto_main.py \
      --character character_prompts.olaf \
      --scenario scenarios.olaf_retells_red_riding_hood_derail \
      --time-limit 5 \
      --run-id 1

This runner will:
- keep the process within the requested time limit
- force the story to close if time is running out
- if the story finishes early, wait until the original limit before exiting
"""

import argparse
import importlib
import json
import os
import sys
import time
from statistics import mean

from dotenv import load_dotenv
from openai import OpenAI

CURRENT_DIR = os.path.dirname(__file__)
IMPLEMENTATION_DIR = os.path.dirname(CURRENT_DIR)
sys.path.append(IMPLEMENTATION_DIR)

from time_control import TemporalMonitor
from time_director_core import get_time_director_decision


def make_client() -> OpenAI:
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def load_module(module_name: str):
    return importlib.import_module(module_name)


MODEL = "gpt-4o-mini"


ACTOR_SYSTEM_PROMPT = """
You are an interactive storytelling engine for an AI character.

You speak as the character.
You must stay in character and follow the Director Agent's instruction.
""".strip()


ACTOR_INSTRUCTIONS = """
You are controlling an interactive AI character.

You must speak as the character.
Follow the Director Agent's instruction, but keep the response natural,
character-consistent, and performable aloud.

## Actor Rules

- Speak only as the character.
- Do not mention the Director Agent.
- Do not explain the system.
- If the user interrupted, answer briefly and return to the story.
- If the user helped the story, incorporate their idea.
- If the user is off-topic, gently redirect.
- Keep the response short: 2 to 4 sentences.
- Choose exactly one animation from the available animation list.
- Do not invent new animations.
- The response must contain a concrete new story development, not just commentary.
- The director_instruction is mandatory. Realize the event described there.

## Time-Constrained Actor Rules

- If pacing_mode is normal: tell the current beat naturally.
- If pacing_mode is hurry: make faster progress and avoid lingering.
- If pacing_mode is critical: compress story events and move toward the ending.
- If pacing_mode is final: immediately give a clear and satisfying ending.
- Do not spend too much time answering derailments when time is low.
- The story must feel complete by the end.

## Anti-Repetition Rules

- Do not start most turns with "Oh".
- Do not use "Oh" in consecutive turns.
- Do not repeat the same catchphrases or patterns.
- Vary the emotional shape of the response.
- Prefer concrete scene details over generic filler.

## Output Format

Return valid JSON only.
""".strip()


class StrictTemporalMonitor(TemporalMonitor):
    def __init__(
        self,
        time_limit_minutes: float,
        total_beats: int,
        final_buffer_seconds: float = 10.0,
        min_turn_buffer_seconds: float = 5.0,
        safety_multiplier: float = 1.5,
    ):
        super().__init__(
            time_limit_minutes=time_limit_minutes,
            total_beats=total_beats,
            final_buffer_seconds=final_buffer_seconds,
        )
        self.min_turn_buffer_seconds = min_turn_buffer_seconds
        self.safety_multiplier = safety_multiplier
        self.turn_durations = []

    def record_turn_duration(self, duration_seconds: float):
        self.turn_durations.append(duration_seconds)

    def average_turn_duration(self) -> float:
        if not self.turn_durations:
            return 7.0
        return max(2.0, mean(self.turn_durations))

    def can_start_next_turn(self) -> bool:
        expected_turn = max(
            self.min_turn_buffer_seconds,
            self.average_turn_duration() * self.safety_multiplier,
        )
        return self.remaining_seconds() > expected_turn

    def pacing_mode(self, beat_index: int) -> str:
        if self.remaining_seconds() <= self.final_buffer_seconds:
            return "final"
        return super().pacing_mode(beat_index)


def build_actor_prompt(
    user_input: str,
    story_state: dict,
    director_decision: dict,
    character: dict,
    story_topic: str,
    beats: list,
    temporal_state: dict,
) -> str:
    current_beat = beats[story_state["beat_index"]]
    current_index = story_state["beat_index"]
    next_beat = beats[current_index + 1]["name"] if current_index < len(beats) - 1 else "None"

    beat_status_hint = (
        f"You are currently in beat '{current_beat['name']}'. "
        f"Your main job is to realize this beat goal: {current_beat['goal']} "
        f"and move toward next beat: {next_beat}."
    )

    return f"""
{ACTOR_INSTRUCTIONS}

## Character

Name:
{character['name']}

Character Prompt:
{character['character_prompt']}

Available animations:
{json.dumps(character['available_animations'], indent=2)}

## Story Topic

{story_topic}

## Current Beat

{current_beat['name']}: {current_beat['goal']}

## Next Beat

{next_beat}

## Beat Status Reminder

{beat_status_hint}

## Completed Beats

{json.dumps(story_state['completed_beats'], indent=2)}

## Turns Spent In Current Beat

{story_state.get('turns_in_current_beat', 0)}

## Story So Far

{story_state['story_so_far']}

## Temporal State

{json.dumps(temporal_state, indent=2)}

## Latest User Input

{user_input}

## Director Decision

{json.dumps(director_decision, indent=2)}

## Output Format

Return valid JSON only in this exact structure:

{{
  "character_response": "What {character['name']} says to the user.",
  "story_event": "One sentence describing what changed in the story.",
  "animation": "one animation from the available list",
  "beat_completed": false,
  "reason": "Briefly explain why the beat is or is not complete."
}}
""".strip()


def safe_json_parse(raw: str, fallback: dict) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        fallback["raw_model_response"] = raw
        return fallback


def validate_animation(animation: str, character: dict) -> str:
    if animation in character["available_animations"]:
        return animation
    return character["available_animations"][0]


def should_complete_beat(
    actor_output: dict,
    director_decision: dict,
    story_state: dict,
    beats: list,
    temporal_state: dict,
) -> bool:
    current_beat_name = beats[story_state["beat_index"]]["name"]
    pacing_mode = temporal_state.get("pacing_mode", "normal")

    if director_decision.get("should_complete_beat") is True:
        return True

    if actor_output.get("beat_completed") is True:
        return True

    if director_decision.get("decision_type") == "close_story":
        return True

    if pacing_mode in ["critical", "final"] and story_state.get("turns_in_current_beat", 0) >= 1:
        return True

    if story_state.get("turns_in_current_beat", 0) >= 3:
        return True

    return False


def should_close_story(director_decision: dict, temporal_state: dict) -> bool:
    if director_decision.get("decision_type") == "close_story":
        return True

    if temporal_state.get("pacing_mode") == "final":
        return True

    return False


def choose_user_input(
    turn_idx: int,
    scenario_inputs: list,
    remaining_seconds: float,
    story_complete: bool,
) -> str:
    if turn_idx <= len(scenario_inputs):
        return scenario_inputs[turn_idx - 1]

    if remaining_seconds <= 15.0 and not story_complete:
        return "Please finish the story in the remaining time with a clear ending."

    return "Please continue the story in the remaining time."


def wait_for_time_limit(start_time: float, time_limit_seconds: float):
    remaining = time_limit_seconds - (time.time() - start_time)
    if remaining > 0:
        time.sleep(remaining)


def run_story(
    character_module: str,
    scenario_module: str,
    run_id: int,
    time_limit: float,
) -> str:
    load_dotenv(os.path.join(IMPLEMENTATION_DIR, ".env"))
    client = make_client()

    character_mod = load_module(character_module)
    scenario_mod = load_module(scenario_module)

    character = character_mod.CHARACTER
    scenario = scenario_mod.SCENARIO

    story_topic = scenario["story_topic"]
    beats = scenario["beats"]
    user_inputs = scenario.get("user_inputs", [])
    scenario_name = scenario["scenario_name"]
    scenario_folder = scenario_module.split(".")[-1]

    monitor = StrictTemporalMonitor(
        time_limit_minutes=time_limit,
        total_beats=len(beats),
        final_buffer_seconds=12.0,
        min_turn_buffer_seconds=5.0,
        safety_multiplier=1.4,
    )

    story_state = {
        "beat_index": 0,
        "completed_beats": [],
        "story_so_far": "",
        "turns_in_current_beat": 0,
    }

    output_dir = os.path.join(
        IMPLEMENTATION_DIR,
        "outputs",
        "time_strict_director_agent",
        scenario_folder,
        f"{time_limit}min",
    )
    os.makedirs(output_dir, exist_ok=True)

    transcript = []
    start_time = time.time()
    turn_idx = 1

    while story_state["beat_index"] < len(beats):
        temporal_state = monitor.state(story_state["beat_index"], beats)
        remaining_seconds = temporal_state["remaining_seconds"]

        if monitor.should_stop_for_time():
            break

        if not monitor.can_start_next_turn() and story_state["beat_index"] < len(beats):
            if remaining_seconds > 3.0:
                user_input = "Please finish the story now in the remaining time."
            else:
                break
        else:
            user_input = choose_user_input(
                turn_idx=turn_idx,
                scenario_inputs=user_inputs,
                remaining_seconds=remaining_seconds,
                story_complete=story_state["beat_index"] >= len(beats),
            )

        story_state["turns_in_current_beat"] += 1

        director_decision = get_time_director_decision(
            client=client,
            model=MODEL,
            user_input=user_input,
            story_state=story_state,
            character=character,
            story_topic=story_topic,
            beats=beats,
            temporal_state=temporal_state,
        )

        if remaining_seconds <= 15.0 and story_state["beat_index"] < len(beats):
            director_decision["decision_type"] = "close_story"
            director_decision["should_complete_beat"] = True
            director_decision["director_instruction"] = (
                "Finish the remaining story quickly and deliver a satisfying ending "
                "within the remaining time."
            )

        prompt = build_actor_prompt(
            user_input=user_input,
            story_state=story_state,
            director_decision=director_decision,
            character=character,
            story_topic=story_topic,
            beats=beats,
            temporal_state=temporal_state,
        )

        call_start = time.time()
        response = client.chat.completions.create(
            model=MODEL,
            temperature=0.45,
            messages=[
                {"role": "system", "content": ACTOR_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        call_duration = time.time() - call_start
        monitor.record_turn_duration(call_duration)

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

        transcript.append({
            "method": "time_strict_director_agent",
            "character": character["name"],
            "scenario": scenario_name,
            "run_id": run_id,
            "turn_index": turn_idx,
            "time_limit_minutes": time_limit,
            "beat": beats[story_state["beat_index"]]["name"],
            "user_input": user_input,
            "temporal_state": temporal_state,
            "director_decision": director_decision,
            "actor_output": actor_output,
        })

        story_state["story_so_far"] += (
            f"\nUser: {user_input}"
            f"\nTemporal Mode: {temporal_state['pacing_mode']}"
            f"\nDirector Decision: {director_decision.get('decision_type')}"
            f"\nDirector Instruction: {director_decision.get('director_instruction')}"
            f"\n{character['name']}: {actor_output['character_response']}"
            f"\nEvent: {actor_output['story_event']}\n"
        )

        if should_complete_beat(
            actor_output=actor_output,
            director_decision=director_decision,
            story_state=story_state,
            beats=beats,
            temporal_state=temporal_state,
        ):
            story_state["completed_beats"].append(beats[story_state["beat_index"]]["name"])
            story_state["beat_index"] += 1
            story_state["turns_in_current_beat"] = 0

        if should_close_story(director_decision, temporal_state):
            break

        turn_idx += 1

    if story_state["beat_index"] >= len(beats):
        # If the story completed early, wait so the process still respects the requested limit.
        wait_for_time_limit(start_time, time_limit * 60)

    transcript_path = os.path.join(output_dir, f"run_{run_id}.json")
    with open(transcript_path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)

    print(f"[time_strict_director_agent] saved: {transcript_path}")
    return transcript_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", required=True, help="e.g. character_prompts.olaf")
    parser.add_argument("--scenario", required=True, help="e.g. scenarios.olaf_retells_red_riding_hood_derail")
    parser.add_argument("--run-id", type=int, default=1)
    parser.add_argument("--time-limit", type=float, default=5.0)
    args = parser.parse_args()

    run_story(
        character_module=args.character,
        scenario_module=args.scenario,
        run_id=args.run_id,
        time_limit=args.time_limit,
    )


if __name__ == "__main__":
    main()
