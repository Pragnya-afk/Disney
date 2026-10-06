"""
director_agent/auto_main_fulltext.py

FULL-TEXT variant of the non-interactive director-agent run. Same
two-call-per-turn shape as auto_main.py (director decision, then
actor), but driven by the complete prose text of the story instead of
a beat list, using director_core_fulltext / director_prompt_fulltext.

Everything else -- character, user_inputs (including derailment
turns), actor anti-repetition/style rules, opener guard -- is kept
identical to auto_main.py so this isolates the story-representation
variable (beats vs. full text) for comparison against the existing
outputs/director_agent/ runs.

Usage (from Implementation/):
    python director_agent/auto_main_fulltext.py \
      --character character_prompts.olaf \
      --scenario scenarios.olaf_derailment_scenario_suite \
      --scenario-name olaf_retells_red_riding_hood_no_derailment \
      --run-id 1
"""

import os
import sys
import json
import argparse
import importlib
from dotenv import load_dotenv
from openai import OpenAI

CURRENT_DIR = os.path.dirname(__file__)
IMPLEMENTATION_DIR = os.path.dirname(CURRENT_DIR)
sys.path.append(IMPLEMENTATION_DIR)

from director_core_fulltext import get_director_decision_fulltext

load_dotenv(os.path.join(IMPLEMENTATION_DIR, ".env"))


def make_client() -> OpenAI:
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


from config import DIRECTOR_BATCH_MODEL

MODEL = DIRECTOR_BATCH_MODEL


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

## Anti-Repetition Rules

- Do not start most turns with "Oh".
- Do not use "Oh" in consecutive turns.
- Do not repeatedly use phrases like:
  - "Isn't that..."
  - "What a..."
  - "It's like..."
  - "I love that..."
  - "That's a great question..."
- Do not end multiple turns with a rhetorical question.
- Do not reuse the same cozy metaphor style every turn.
- If you used a snow, hug, or warmth metaphor recently, avoid using another one unless truly necessary.
- Vary the emotional shape of the response:
  - sometimes excited
  - sometimes curious
  - sometimes concerned
  - sometimes gentle
  - sometimes direct
- Prefer concrete scene details over generic Olaf filler.

## Strong Style Rule

The response must sound like Olaf, but not like the same Olaf sentence pattern every turn.
Character fidelity must come from tone and warmth, not from repeating the same catchphrases.

## Response Balance Rule

If the user input is disruptive or off-track:
- acknowledge it in at most one short sentence
- spend the rest of the response on the story event

The story event is more important than the acknowledgment.

Do not let the acknowledgment dominate the response.

## Storytelling Rules

- After acknowledging the user, spend most of the response on the story itself.
- Each response should push the retelling forward with at least one new event, reveal, or shift.
- Do not stay in commentary mode for the whole turn.
- If the director indicates a concrete event, that event must happen in the response.

## Output Format

Return valid JSON only.
""".strip()


def load_module(module_name: str):
    return importlib.import_module(module_name)


def load_scenario(scenario_module: str, scenario_name: str | None) -> dict:
    mod = load_module(scenario_module)
    if scenario_name:
        if not hasattr(mod, "SCENARIOS"):
            raise ValueError("--scenario-name requires a suite module with a SCENARIOS dict.")
        if scenario_name not in mod.SCENARIOS:
            raise ValueError(f"Scenario '{scenario_name}' not found. Available: {list(mod.SCENARIOS.keys())}")
        return mod.SCENARIOS[scenario_name]
    return mod.SCENARIO


def build_actor_prompt_fulltext(
    user_input: str,
    story_state: dict,
    director_decision: dict,
    character: dict,
    full_story_text: str,
) -> str:
    turns_since_progress = story_state.get("turns_since_progress", 0)

    progress_hint = (
        f"You have gone {turns_since_progress} turn(s) without advancing further through the "
        f"story text. Your main job is to realize the director's instruction and move further "
        f"through the story."
    )

    return f"""
{ACTOR_INSTRUCTIONS}

## Character

Name:
{character["name"]}

Character Prompt:
{character["character_prompt"]}

Available animations:
{json.dumps(character["available_animations"], indent=2)}

## Full Story Text

{full_story_text}

## Progress Reminder

{progress_hint}

## Story So Far

{story_state["story_so_far"]}

## Latest User Input

{user_input}

## Director Decision

{json.dumps(director_decision, indent=2)}

## Output Format

Return valid JSON only in this exact structure:

{{
  "character_response": "What {character["name"]} says to the user.",
  "story_event": "One sentence describing what changed in the story.",
  "animation": "one animation from the available list",
  "story_advanced": false,
  "reason": "Briefly explain why the story did or did not advance this turn."
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


def run_story_fulltext(
    character_module: str,
    scenario_module: str,
    full_story_text: str,
    run_id: int,
    scenario_name_override: str | None = None,
) -> str:
    client = make_client()

    character_mod = load_module(character_module)
    character = character_mod.CHARACTER
    scenario = load_scenario(scenario_module, scenario_name_override)

    user_inputs = scenario["user_inputs"]
    scenario_name = scenario["scenario_name"]

    story_state = {
        "story_so_far": "",
        "turns_since_progress": 0,
    }

    output_dir = os.path.join(
        IMPLEMENTATION_DIR,
        "outputs",
        "director_agent_fulltext",
        scenario_name,
        "batch",
    )
    os.makedirs(output_dir, exist_ok=True)

    transcript = []

    for turn_idx, user_input in enumerate(user_inputs, start=1):
        director_decision = get_director_decision_fulltext(
            client=client,
            model=MODEL,
            user_input=user_input,
            story_state=story_state,
            character=character,
            full_story_text=full_story_text,
        )

        prompt = build_actor_prompt_fulltext(
            user_input=user_input,
            story_state=story_state,
            director_decision=director_decision,
            character=character,
            full_story_text=full_story_text,
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
                "story_advanced": False,
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
            "method": "director_agent_fulltext",
            "character": character["name"],
            "scenario": scenario_name,
            "run_id": run_id,
            "turn_index": turn_idx,
            "user_input": user_input,
            "director_decision": director_decision,
            "actor_output": actor_output,
        })

        advanced = bool(director_decision.get("should_advance_story")) or bool(actor_output.get("story_advanced"))
        story_state["turns_since_progress"] = 0 if advanced else story_state["turns_since_progress"] + 1

        if director_decision.get("decision_type") == "close_story":
            break

    transcript_path = os.path.join(output_dir, f"run_{run_id}.json")

    with open(transcript_path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)

    print(f"[director_agent_fulltext] saved: {transcript_path}")
    return transcript_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", required=True, help="e.g. character_prompts.olaf")
    parser.add_argument("--scenario", required=True, help="e.g. scenarios.olaf_derailment_scenario_suite")
    parser.add_argument("--scenario-name", default=None)
    parser.add_argument("--run-id", type=int, default=1)
    args = parser.parse_args()

    from scenarios.red_riding_hood_full_text import FULL_STORY_TEXT

    run_story_fulltext(args.character, args.scenario, FULL_STORY_TEXT, args.run_id, args.scenario_name)


if __name__ == "__main__":
    main()
