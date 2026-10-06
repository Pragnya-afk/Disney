"""
run_baseline_fulltext_rrh.py

Ablation: full-story-text baseline for the Olaf "Little Red Riding
Hood" derailment suite, to compare against the existing beats-based
baseline/director runs.

Instead of a structured beat list (`## Narrative Arc` + `## Current
Beat` + a `beat_completed` flag the system checks each turn), the
model is handed the complete prose text of the story up front and has
to track its own progress and decide for itself when the story is
over (`story_complete` flag it sets, not a beat index the harness
tracks). Character, user_inputs (including the derailment turns), and
everything else stay identical to the beats-based run, so the two are
directly comparable turn-by-turn.

Scope: red-riding-hood scenarios only (7 variants), Olaf character.
This does NOT run these outputs through the evaluator -- it just
produces transcripts under outputs/baseline_fulltext/ for review.

Usage (from Implementation/):
    python run_baseline_fulltext_rrh.py
    python run_baseline_fulltext_rrh.py --dry-run
"""

import argparse
import json
import os
import sys
from pathlib import Path

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CURRENT_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(CURRENT_DIR, ".env"))

from openai import OpenAI
from scenarios.olaf_derailment_scenario_suite import SCENARIOS
from character_prompts.olaf import CHARACTER

RUN_ID = 1
MODEL = "gpt-4o-mini"

FULL_STORY_TEXT = """
Once upon a time, in a village at the edge of a great forest, there lived a
little girl everyone called Little Red Riding Hood, because of the red
hooded cloak her grandmother had made for her.

One morning, her mother packed a basket with fresh bread, butter, and a
bottle of wine and said, "Your grandmother is unwell. Take this basket to
her cottage on the other side of the forest, but go straight there -- do
not wander off the path, and do not stop to talk to strangers."

Little Red Riding Hood promised, kissed her mother goodbye, and set off
down the forest path with her basket.

The forest was beautiful that morning. Sunlight fell in golden patches
through the leaves, birds sang overhead, and wildflowers grew thick along
the path. Little Red Riding Hood slowed again and again, delighted by
every butterfly and every rustle in the branches, almost forgetting to
hurry as she wandered a little further from the path than she meant to.

Before long, a wolf stepped out from among the trees. He was cunning, and
instead of pouncing at once, he asked her sweetly where she was going. Not
knowing how dangerous he was, she told him she was bringing food to her
sick grandmother, who lived in a cottage further into the woods.

The wolf suggested she pick some flowers for her grandmother, to cheer her
up. While Little Red Riding Hood wandered off the path gathering flowers,
the wolf ran ahead by the shortest route to the grandmother's cottage.

He knocked at the door, imitating the girl's voice, and when the
grandmother opened it, he swallowed her whole. Then he put on her
nightclothes and cap and climbed into her bed to wait.

When Little Red Riding Hood finally reached the cottage, something felt
different. The door stood slightly ajar and the house was unusually
quiet -- no humming, no clatter of dishes, none of the small sounds she
knew from visiting before. A strange unease crept over her, though she
could not have said why. She knocked softly, and the wolf called out in a
hoarse voice for her to come in. She told herself her grandmother simply
had a cold. Stepping inside, she noticed how strange her grandmother
looked.

"Grandmother, what big ears you have!"
"All the better to hear you with, my dear."
"Grandmother, what big eyes you have!"
"All the better to see you with, my dear."
"Grandmother, what big teeth you have!"
"All the better to eat you with!" -- and the wolf leapt from the bed and
swallowed her too.

A woodsman passing by the cottage heard the commotion and rushed inside.
Seeing the wolf's stomach still moving, he cut it open with his axe, and
out stepped Little Red Riding Hood and her grandmother, frightened but
unharmed. They filled the wolf's stomach with heavy stones, and when he
woke and tried to run, he collapsed, and that was the end of him.

Little Red Riding Hood promised herself that from then on, she would
always listen to her mother and never stray from the path or trust a
stranger in the woods.

THE END.
""".strip()


def call_llm(client, prompt):
    response = client.chat.completions.create(
        model=MODEL,
        temperature=0.7,
        messages=[
            {
                "role": "system",
                "content": "You are an interactive storytelling engine for an AI character.",
            },
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content.strip()


def build_prompt(user_input, story_so_far, character, full_text):
    return f"""
You are controlling an interactive AI character.

This is a FULL-TEXT baseline system: instead of a structured
beat-by-beat outline, you are given the complete text of the story
below. Narrate it interactively to the user, adapting to their input
while staying in character. Track your own progress through the
story yourself -- there is no external beat tracker telling you what
happens next or when a section is done.

- Respond naturally to the user's input.
- Keep the response short and performable aloud.
- The response should contain at least one concrete story event.
- Decide for yourself when the full story has been told to the user,
  and set "story_complete" to true only once it truly has.

Return valid JSON only.

## Character
Name: {character["name"]}

Character Prompt:
{character["character_prompt"]}

Available animations:
{json.dumps(character["available_animations"], indent=2)}

## Full Story Text
{full_text}

## Story So Far (already narrated to the user this session)
{story_so_far if story_so_far else "(nothing narrated yet)"}

## Latest User Input
{user_input}

## Output Format
{{
  "character_response": "What the character says to the user.",
  "story_event": "One sentence describing what changed in the story.",
  "animation": "one animation from the available list",
  "story_complete": false,
  "reason": "Briefly explain why the story is or is not complete."
}}
""".strip()


def safe_parse(raw, fallback_animation):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "character_response": raw,
            "story_event": "The story continued.",
            "animation": fallback_animation,
            "story_complete": False,
            "reason": "Model did not return valid JSON.",
        }


def validate_animation(animation, character):
    if animation in character["available_animations"]:
        return animation
    return character["available_animations"][0]


def run_fulltext(scenario: dict, character: dict, run_id: int) -> str:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    scenario_name = scenario["scenario_name"]
    user_inputs = scenario["user_inputs"]

    output_dir = os.path.join(CURRENT_DIR, "outputs", "baseline_fulltext", scenario_name, "batch")
    os.makedirs(output_dir, exist_ok=True)

    story_so_far = ""
    transcript = []

    for turn_idx, user_input in enumerate(user_inputs, start=1):
        prompt = build_prompt(user_input, story_so_far, character, FULL_STORY_TEXT)
        raw = call_llm(client, prompt)
        output = safe_parse(raw, character["available_animations"][0])
        output["animation"] = validate_animation(output.get("animation", ""), character)

        story_so_far += (
            f"\nUser: {user_input}"
            f"\n{character['name']}: {output['character_response']}"
            f"\nEvent: {output['story_event']}\n"
        )

        transcript.append({
            "method": "baseline_fulltext",
            "character": character["name"],
            "scenario": scenario_name,
            "run_id": run_id,
            "turn_index": turn_idx,
            "user_input": user_input,
            "model_output": output,
        })

        if output.get("story_complete") is True:
            break

    out_path = os.path.join(output_dir, f"run_{run_id}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)

    print(f"  [baseline_fulltext] saved -> {out_path}")
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print what would run without executing.")
    args = parser.parse_args()

    scenario_list = sorted(n for n in SCENARIOS if "retells_red_riding_hood" in n)
    print(f"Suite: {len(scenario_list)} red-riding-hood scenarios\n")

    todo = []
    for name in scenario_list:
        out = Path(CURRENT_DIR) / "outputs" / "baseline_fulltext" / name / "batch" / f"run_{RUN_ID}.json"
        if out.exists():
            print(f"  [skip] {name}")
        else:
            todo.append(SCENARIOS[name])

    print(f"\nTo run: {len(todo)} scenarios")

    if args.dry_run:
        print("\n-- dry run, not executing --")
        for sc in todo:
            print(f"  {sc['scenario_name']}")
        return

    if not todo:
        print("Nothing to run.")
        return

    completed, failed = 0, []
    for i, sc in enumerate(todo, 1):
        name = sc["scenario_name"]
        print(f"\n[{i}/{len(todo)}] {name}")
        try:
            run_fulltext(sc, CHARACTER, RUN_ID)
            completed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed.append((name, str(e)))

    print(f"\n{'='*60}")
    print(f"Done. {completed}/{len(todo)} succeeded, {len(failed)} failed.")
    if failed:
        print("\nFailed runs:")
        for name, err in failed:
            print(f"  {name}: {err}")


if __name__ == "__main__":
    main()
