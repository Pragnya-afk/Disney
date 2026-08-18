"""
beat_generator/beat_generator.py

Turns a free-text story prompt into a director-ready beat list, shaped
exactly like a BASE_STORIES entry in
Implementation/scenarios/olaf_derailment_scenario_suite.py:
{base_name, story_length, narrative_mode, story_topic,
 beats: [{name, importance, goal, expansions}]}.

One generation call serves all three director modes — `importance` and
`expansions` are always populated, since time_constrained mode is the only
one that additionally relies on them and there's no reason to special-case
the prompt per mode.
"""

import json
import re

from openai import OpenAI

VALID_IMPORTANCE = {"high", "medium", "low"}
MIN_BEATS = 4
MAX_BEATS = 8

_SNAKE_RE = re.compile(r"[^a-z0-9]+")


def _snake_case(text: str) -> str:
    text = (text or "").strip().lower()
    text = _SNAKE_RE.sub("_", text).strip("_")
    return text or "beat"


def build_beat_generation_prompt(
    story_prompt: str,
    character: dict,
    target_beats: int = 6,
    expansions_per_beat: int = 3,
) -> str:
    return f"""
You are designing the beat structure for an interactive storytelling session
narrated in character by {character["name"]}.

{character["character_prompt"]}

## User's Story Idea

{story_prompt}

## Task

Design a beat-by-beat story structure for this idea, told in {character["name"]}'s
voice. Produce approximately {target_beats} beats (between {MIN_BEATS} and {MAX_BEATS}) that
form a coherent narrative arc with a clear beginning, rising development, and
a satisfying ending.

For each beat, also produce {expansions_per_beat} "expansions" — optional extra
material a director can use to stretch that beat with more detail if the
story is running ahead of schedule. Expansions should be concrete, specific
additions (a sensory detail, a small character beat, an extra exchange) —
not vague filler instructions.

## Output Format

Return valid JSON only, in exactly this structure:

{{
  "base_name": "short_snake_case_story_id",
  "story_length": "short",
  "narrative_mode": "experience_manager_present",
  "story_topic": "One to three sentences describing the story and how {character["name"]} should tell it.",
  "beats": [
    {{
      "name": "short_snake_case_beat_name",
      "importance": "high",
      "goal": "One sentence describing what must happen in this beat.",
      "expansions": ["Concrete optional detail to add if there's time.", "..."]
    }}
  ]
}}

Rules:
- "importance" must be exactly one of: "high", "medium", "low".
- The first and last beats should be "high" importance.
- Beat names must be unique, short, and snake_case.
- "story_length" should be one of: very_short, short, medium, medium_long, long, very_long.
- Output only the JSON object, nothing else.
""".strip()


def validate_and_repair(spec: dict) -> tuple[dict, list[str]]:
    """Enforce the schema's hard constraints, coercing what can be safely
    coerced and warning about what can't. Never raises — always returns a
    usable spec so the caller can decide whether the warnings matter.
    """
    warnings: list[str] = []
    spec = dict(spec) if isinstance(spec, dict) else {}

    spec["base_name"] = _snake_case(spec.get("base_name") or "generated_story")
    spec["story_length"] = spec.get("story_length") or "medium"
    spec["narrative_mode"] = spec.get("narrative_mode") or "experience_manager_present"
    spec["story_topic"] = (spec.get("story_topic") or "").strip()
    if not spec["story_topic"]:
        spec["story_topic"] = "An interactive story."
        warnings.append("story_topic was empty; used a generic placeholder.")

    raw_beats = spec.get("beats")
    if not isinstance(raw_beats, list) or not raw_beats:
        warnings.append("No beats were generated.")
        spec["beats"] = []
        return spec, warnings

    beats = []
    seen_names = set()
    for i, b in enumerate(raw_beats):
        if not isinstance(b, dict):
            continue
        name = _snake_case(b.get("name") or f"beat_{i + 1}")
        base_name = name
        suffix = 2
        while name in seen_names:
            name = f"{base_name}_{suffix}"
            suffix += 1
        seen_names.add(name)

        importance = b.get("importance")
        if importance not in VALID_IMPORTANCE:
            if importance is not None:
                warnings.append(f"beat '{name}': invalid importance '{importance}', coerced to 'medium'.")
            importance = "medium"

        goal = (b.get("goal") or "").strip()
        if not goal:
            goal = f"Advance the story through the '{name.replace('_', ' ')}' moment."
            warnings.append(f"beat '{name}': missing goal, used a generic placeholder.")

        expansions = b.get("expansions")
        if not isinstance(expansions, list) or not expansions:
            expansions = [f"Add more sensory or emotional detail to '{name.replace('_', ' ')}'."]
            warnings.append(f"beat '{name}': missing expansions, used a generic placeholder.")
        expansions = [str(e).strip() for e in expansions if str(e).strip()]

        beats.append({"name": name, "importance": importance, "goal": goal, "expansions": expansions})

    if len(beats) > MAX_BEATS:
        first, last = beats[0], beats[-1]
        middle = beats[1:-1]
        rank = {"high": 0, "medium": 1, "low": 2}
        middle_sorted = sorted(middle, key=lambda b: rank.get(b["importance"], 1))
        keep_middle = middle_sorted[: max(0, MAX_BEATS - 2)]
        keep_names = {b["name"] for b in keep_middle}
        beats = [first] + [b for b in middle if b["name"] in keep_names] + [last]
        warnings.append(f"trimmed beats down to {len(beats)} (max {MAX_BEATS}), keeping highest-importance middle beats.")

    if len(beats) < MIN_BEATS:
        warnings.append(f"only {len(beats)} beats generated (recommended minimum {MIN_BEATS}).")

    if beats:
        if beats[0]["importance"] != "high":
            beats[0]["importance"] = "high"
        if beats[-1]["importance"] != "high":
            beats[-1]["importance"] = "high"

    spec["beats"] = beats
    return spec, warnings


def generate_story_spec(
    client: OpenAI,
    model: str,
    story_prompt: str,
    character: dict,
    target_beats: int = 6,
    expansions_per_beat: int = 3,
) -> dict:
    """One-shot generation of a director-ready story spec from a free-text
    prompt. Returns the validated/repaired spec with a "_warnings" key
    listing anything that had to be coerced.
    """
    prompt = build_beat_generation_prompt(
        story_prompt=story_prompt,
        character=character,
        target_beats=target_beats,
        expansions_per_beat=expansions_per_beat,
    )

    response = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": "You design beat structures for interactive children's stories. Output only JSON.",
            },
            {"role": "user", "content": prompt},
        ],
    )

    raw = response.choices[0].message.content.strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {}

    spec, warnings = validate_and_repair(parsed)
    spec["_warnings"] = warnings
    return spec


def spec_to_scenario(spec: dict, story_id: str) -> dict:
    """Wrap a generated spec into the shape the story-starting code
    (_new_story / _resolve_scenario) consumes — the same shape as an entry
    read out of the fixed scenario registry.
    """
    return {
        "scenario_name": story_id,
        "story_topic": spec.get("story_topic", ""),
        "beats": spec.get("beats", []),
        "title": spec.get("base_name", story_id).replace("_", " ").title(),
    }
