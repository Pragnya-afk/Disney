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
import importlib
from dotenv import load_dotenv
from openai import OpenAI

CURRENT_DIR = os.path.dirname(__file__)
IMPLEMENTATION_DIR = os.path.dirname(CURRENT_DIR)
sys.path.append(IMPLEMENTATION_DIR)

from director_core import get_director_decision

load_dotenv(os.path.join(IMPLEMENTATION_DIR, ".env"))

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
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


def build_actor_prompt(
    user_input: str,
    story_state: dict,
    director_decision: dict,
    character: dict,
    story_topic: str,
    beats: list,
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
{character["name"]}

Character Prompt:
{character["character_prompt"]}

Available animations:
{json.dumps(character["available_animations"], indent=2)}

## Story Topic

{story_topic}

## Current Beat

{current_beat["name"]}: {current_beat["goal"]}

## Next Beat

{next_beat}

## Beat Status Reminder

{beat_status_hint}

## Completed Beats

{json.dumps(story_state["completed_beats"], indent=2)}

## Turns Spent In Current Beat

{story_state.get("turns_in_current_beat", 0)}

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
  "beat_completed": false,
  "reason": "Briefly explain why the beat is or is not complete."
}}
""".strip()


def safe_json_parse(raw: str, fallback: dict) -> dict:
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


def validate_animation(animation: str, character: dict) -> str:
    if animation in character["available_animations"]:
        return animation
    return character["available_animations"][0]


def text_indicates_next_beat(actor_output: dict, current_beat_name: str) -> bool:
    text = (
        actor_output.get("character_response", "") + " " +
        actor_output.get("story_event", "")
    ).lower()

    beat_to_keywords = {
        "story_opening": [
            "mother warned", "stay on the path", "entered the forest", "into the forest"
        ],
        "home_and_family_setup": [
            "stay on the path", "avoid strangers", "entered the forest", "into the woods"
        ],
        "warning_before_departure": [
            "entered the forest", "into the forest", "flowers", "birds", "wolf"
        ],
        "forest_entry": [
            "wolf", "talked to the wolf", "charming wolf", "asked where she was going"
        ],
        "forest_distraction": [
            "wolf", "grandmother's cottage", "where does your grandmother live"
        ],
        "wolf_appears": [
            "shared details", "grandmother's cottage", "butterfly", "off the path"
        ],
        "conversation_and_disclosure": [
            "cottage", "door", "inside", "disguised", "grandmother in bed"
        ],
        "wolf_manipulates_delay": [
            "big eyes", "big teeth", "revealed his true nature", "lunged"
        ],
        "wolf_reaches_cottage_first": [
            "woodcutter", "rescued", "safe now", "grandmother emerged"
        ],
        "grandmother_in_danger": [
            "reflected", "lessons learned", "shared treats", "safe together"
        ],
        "red_approaches_cottage": [
            "lessons learned", "shared treats", "safe together", "look out for each other"
        ],
    }

    keywords = beat_to_keywords.get(current_beat_name, [])
    return any(keyword in text for keyword in keywords)


def should_complete_beat(
    actor_output: dict,
    director_decision: dict,
    story_state: dict,
    beats: list,
) -> bool:
    current_beat_name = beats[story_state["beat_index"]]["name"]

    if director_decision.get("should_complete_beat") is True:
        return True

    if actor_output.get("beat_completed") is True:
        return True

    if text_indicates_next_beat(actor_output, current_beat_name):
        return True

    # if story_state.get("turns_in_current_beat", 0) >= 3:
    #     return True
    # The beat should not be forced to complete purely because it has lasted three turns.

    return False


def should_close_story(director_decision: dict) -> bool:
    return director_decision.get("decision_type") == "close_story"


def run(character_module: str, scenario_module: str):
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

    scenario_folder = scenario_module.split('.')[-1]
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

        actor_output["animation"] = validate_animation(
            actor_output.get("animation", ""), character
        )

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

        transcript.append({
            "method": "director_agent",
            "character": character["name"],
            "scenario": scenario["scenario_name"],
            "beat": current_beat["name"],
            "user_input": user_input,
            "director_decision": director_decision,
            "actor_output": actor_output,
        })

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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", required=True, help="e.g. character_prompts.olaf")
    parser.add_argument("--scenario", required=True, help="e.g. scenarios.olaf_retells_red_riding_hood_derail")
    args = parser.parse_args()

    run(args.character, args.scenario)


if __name__ == "__main__":
    main()