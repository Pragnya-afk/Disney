#!/usr/bin/env python3
import argparse
import json
import os
import re
from typing import Any, Dict, List


def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        if path.endswith(".jsonl"):
            return [json.loads(line) for line in f if line.strip()]
        return json.load(f)


def sort_turn_key(key: str) -> int:
    match = re.match(r"turn_(-?\d+)$", key)
    return int(match.group(1)) if match else float("inf")


def is_end_marker(text: str) -> bool:
    if not text:
        return True
    normalized = text.strip()
    return bool(re.match(r"^(PART|ACT|STORY) \d* ENDS$", normalized, re.IGNORECASE))


def extract_story_progress(narrative: Dict[str, Any]) -> List[str]:
    story_texts: List[str] = []

    if any(key.startswith("part_") for key in narrative.keys()):
        for part_key in sorted(
            [key for key in narrative.keys() if key.startswith("part_")],
            key=lambda k: int(k.split("_")[1]),
        ):
            part_data = narrative.get(part_key, {})
            for turn_key in sorted(
                [key for key in part_data.keys() if key.startswith("turn_")],
                key=sort_turn_key,
            ):
                if turn_key == "turn_-1":
                    continue
                story_progress = part_data.get(turn_key, {}).get("story_progress")
                if not story_progress or is_end_marker(story_progress):
                    continue
                story_texts.append(story_progress.strip())
    else:
        for turn_key in sorted(
            [key for key in narrative.keys() if key.startswith("turn_")],
            key=sort_turn_key,
        ):
            if turn_key == "turn_-1":
                continue
            story_progress = narrative.get(turn_key, {}).get("story_progress")
            if not story_progress or is_end_marker(story_progress):
                continue
            story_texts.append(story_progress.strip())

    return story_texts


def build_transcript(
    story_texts: List[str],
    example_id: str,
    scenario: str,
    character: str,
    run_id: int,
) -> List[Dict[str, Any]]:
    transcript = []

    for idx, text in enumerate(story_texts, start=1):
        transcript.append(
            {
                "method": "codi",
                "character": character,
                "scenario": scenario,
                "run_id": run_id,
                "turn_index": idx,
                "beat": f"turn_{idx}",
                "user_input": "",
                "model_output": {
                    "character_response": text,
                    "story_event": text,
                    "animation": "",
                    "beat_completed": False,
                },
            }
        )

    return transcript


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert CoDi JSON output into an Implementation evaluator transcript JSON file."
    )
    parser.add_argument(
        "--codi-json-file",
        required=True,
        help="Path to the CoDi generated JSON file (e.g. gen_plan_*.json).",
    )
    parser.add_argument(
        "--example-id",
        required=True,
        help="Example ID to extract from the CoDi JSON output.",
    )
    parser.add_argument(
        "--output-file",
        required=True,
        help="Path to write the converted transcript JSON file.",
    )
    parser.add_argument(
        "--character",
        default="Olaf",
        help="Character name to set in the converted transcript.",
    )
    parser.add_argument(
        "--scenario",
        default=None,
        help="Scenario name to set in the converted transcript. Defaults to example-id if omitted.",
    )
    parser.add_argument(
        "--run-id",
        type=int,
        default=1,
        help="Run ID to set in the converted transcript.",
    )

    args = parser.parse_args()
    data = load_json(args.codi_json_file)

    if not isinstance(data, list):
        raise ValueError("Expected CoDi output JSON to be a list of examples.")

    example = next((item for item in data if item.get("example_id") == args.example_id), None)
    if example is None:
        raise ValueError(f"Example ID '{args.example_id}' not found in CoDi JSON output.")

    narrative = example.get("narrative", {})
    story_texts = extract_story_progress(narrative)
    if not story_texts:
        raise ValueError(
            f"No story_progress entries found for example '{args.example_id}'."
        )

    transcript = build_transcript(
        story_texts=story_texts,
        example_id=args.example_id,
        scenario=args.scenario or args.example_id,
        character=args.character,
        run_id=args.run_id,
    )

    os.makedirs(os.path.dirname(args.output_file), exist_ok=True)
    with open(args.output_file, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)

    print(f"Converted {len(transcript)} turns for example '{args.example_id}' to {args.output_file}.")


if __name__ == "__main__":
    main()
