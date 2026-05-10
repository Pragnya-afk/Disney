"""
director_agent/main.py

Director-agent implementation.

There are two LLM agents:

1. Director Agent
   - classifies the user's input
   - handles interruptions
   - decides whether to progress or redirect
   - decides whether the beat is complete

2. Actor Agent
   - speaks as the character
   - follows the director instruction
   - chooses animation
   - produces the visible story response

Run from the Implementation folder:

    python director_agent/main.py
"""

import os
import sys
import json
from dotenv import load_dotenv
from openai import OpenAI


# ------------------------------------------------------------
# Import setup
# ------------------------------------------------------------

CURRENT_DIR = os.path.dirname(__file__)
IMPLEMENTATION_DIR = os.path.dirname(CURRENT_DIR)

# Allows imports from Implementation/character_prompts
sys.path.append(IMPLEMENTATION_DIR)


# ------------------------------------------------------------
# Choose character here
# ------------------------------------------------------------

from character_prompts.olaf import CHARACTER, STORY_TOPIC, BEATS

# To use Rocket instead, comment the Olaf import above and uncomment this:
# from character_prompts.rocket import CHARACTER, STORY_TOPIC, BEATS


# Import Director Agent
from director_agent import get_director_decision


# ------------------------------------------------------------
# Environment and OpenAI setup
# ------------------------------------------------------------

load_dotenv(os.path.join(IMPLEMENTATION_DIR, ".env"))

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

MODEL = "gpt-4o-mini"


# ------------------------------------------------------------
# Actor system prompt
# ------------------------------------------------------------

ACTOR_SYSTEM_PROMPT = """
You are an interactive storytelling engine for an AI character.

You speak as the character.
You must stay in character and follow the Director Agent's instruction.
""".strip()


# ------------------------------------------------------------
# Actor instructions
# ------------------------------------------------------------

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
- Keep the response short: 1 to 3 sentences.
- Choose exactly one animation from the available animation list.
- Do not invent new animations.
- The response should help the current beat unless the director says to close the story.
""".strip()


# ------------------------------------------------------------
# Actor prompt builder
# ------------------------------------------------------------

def build_actor_prompt(
    user_input: str,
    story_state: dict,
    director_decision: dict,
) -> str:
    """
    Build the prompt for the Actor Agent.
    """

    current_beat = BEATS[story_state["beat_index"]]

    return f"""
{ACTOR_INSTRUCTIONS}

## Character

Name:
{CHARACTER["name"]}

Character Prompt:
{CHARACTER["character_prompt"]}

Available animations:
{json.dumps(CHARACTER["available_animations"], indent=2)}

## Story Topic

{STORY_TOPIC}

## Narrative Arc

{json.dumps(BEATS, indent=2)}

## Current Beat

{current_beat["name"]}: {current_beat["goal"]}

## Completed Beats

{json.dumps(story_state["completed_beats"], indent=2)}

## Story So Far

{story_state["story_so_far"]}

## Latest User Input

{user_input}

## Director Decision

{json.dumps(director_decision, indent=2)}

## Output Format

Return valid JSON only in this exact structure:

{{
  "character_response": "What {CHARACTER["name"]} says to the user.",
  "story_event": "One sentence describing what changed in the story.",
  "animation": "one animation from the available list",
  "beat_completed": false,
  "reason": "Briefly explain why the beat is or is not complete."
}}
""".strip()


# ------------------------------------------------------------
# Actor Agent call
# ------------------------------------------------------------

def call_actor_agent(
    user_input: str,
    story_state: dict,
    director_decision: dict,
) -> dict:
    """
    Call the Actor Agent.
    """

    prompt = build_actor_prompt(
        user_input=user_input,
        story_state=story_state,
        director_decision=director_decision,
    )

    response = client.chat.completions.create(
        model=MODEL,
        temperature=0.7,
        messages=[
            {
                "role": "system",
                "content": ACTOR_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
    )

    raw = response.choices[0].message.content.strip()

    fallback = {
        "character_response": (
            "Oh! My thoughts just did a tiny tumble. "
            "But I think we can still keep going together!"
        ),
        "story_event": "The character gently redirected the moment back to the story.",
        "animation": CHARACTER["available_animations"][0],
        "beat_completed": False,
        "reason": "Actor response was not valid JSON.",
        "raw_model_response": raw,
    }

    return safe_json_parse(raw, fallback)


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def safe_json_parse(raw: str, fallback: dict) -> dict:
    """
    Safely parse JSON output.

    If parsing fails, return fallback.
    """

    try:
        return json.loads(raw)

    except json.JSONDecodeError:
        return fallback


def validate_animation(animation: str) -> str:
    """
    Ensure selected animation is valid.
    """

    if animation in CHARACTER["available_animations"]:
        return animation

    return CHARACTER["available_animations"][0]


def should_complete_beat(
    actor_output: dict,
    director_decision: dict,
) -> bool:
    """
    Decide whether to complete the current beat.

    The Director Agent has priority over the Actor Agent.
    """

    if director_decision.get("should_complete_beat") is True:
        return True

    if director_decision.get("should_complete_beat") is False:
        return False

    return actor_output.get("beat_completed") is True


def should_close_story(director_decision: dict) -> bool:
    """
    Check whether the Director Agent decided to close the story.
    """

    return director_decision.get("decision_type") == "close_story"


# ------------------------------------------------------------
# Main loop
# ------------------------------------------------------------

def run():
    """
    Run the director-agent interactive storytelling loop.
    """

    story_state = {
        "beat_index": 0,
        "completed_beats": [],
        "story_so_far": "",
    }

    output_dir = os.path.join(CURRENT_DIR, "outputs")
    os.makedirs(output_dir, exist_ok=True)

    transcript = []

    print("\nDirector-agent storytelling started.")
    print(f"Loaded character: {CHARACTER['name']}")
    print("Type your message. Type 'quit' to stop.\n")

    while story_state["beat_index"] < len(BEATS):
        current_beat = BEATS[story_state["beat_index"]]

        print(f"\nCurrent beat: {current_beat['name']}")
        user_input = input("You: ")

        if user_input.lower().strip() in ["quit", "exit", "stop"]:
            break

        # ----------------------------------------------------
        # Step 1: Director Agent decides how to handle input
        # ----------------------------------------------------

        director_decision = get_director_decision(
            client=client,
            model=MODEL,
            user_input=user_input,
            story_state=story_state,
            character=CHARACTER,
            story_topic=STORY_TOPIC,
            beats=BEATS,
        )

        # ----------------------------------------------------
        # Step 2: Actor Agent generates character response
        # ----------------------------------------------------

        actor_output = call_actor_agent(
            user_input=user_input,
            story_state=story_state,
            director_decision=director_decision,
        )

        actor_output["animation"] = validate_animation(
            actor_output.get("animation", CHARACTER["available_animations"][0])
        )

        # ----------------------------------------------------
        # Display output
        # ----------------------------------------------------

        print(f"\nDirector decision: {director_decision.get('decision_type')}")
        print(f"{CHARACTER['name']}: {actor_output['character_response']}")
        print(f"[Animation: {actor_output['animation']}]")

        # ----------------------------------------------------
        # Update story memory
        # ----------------------------------------------------

        story_state["story_so_far"] += (
            f"\nUser: {user_input}"
            f"\nDirector Decision: {director_decision.get('decision_type')}"
            f"\nDirector Instruction: {director_decision.get('director_instruction')}"
            f"\n{CHARACTER['name']}: {actor_output['character_response']}"
            f"\nEvent: {actor_output['story_event']}\n"
        )

        # ----------------------------------------------------
        # Save transcript entry
        # ----------------------------------------------------

        transcript.append({
            "method": "director_agent",
            "character": CHARACTER["name"],
            "beat": current_beat["name"],
            "user_input": user_input,
            "director_decision": director_decision,
            "actor_output": actor_output,
        })

        # ----------------------------------------------------
        # Beat progression
        # ----------------------------------------------------

        if should_complete_beat(actor_output, director_decision):
            story_state["completed_beats"].append(current_beat["name"])
            story_state["beat_index"] += 1

        if should_close_story(director_decision):
            break

    transcript_path = os.path.join(
        output_dir,
        f"director_agent_transcript_{CHARACTER['name'].lower()}.json",
    )

    with open(transcript_path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)

    print("\nStory finished or stopped.")
    print(f"Saved transcript to {transcript_path}")


if __name__ == "__main__":
    run()