"""
evaluation/extract_character_outputs.py

Extract readable character-only outputs from transcript JSON files.

Supports:
1. One file only:
   --input ...
2. Two files:
   --baseline ... --director ...

Examples
--------
Single file:
    python evaluation/extract_character_outputs.py \
      --input outputs/baseline/olaf_retells_red_riding_hood_medium/run_1.json \
      --out evaluation/results/olaf_retells_red_riding_hood_medium/run_1_baseline_character_outputs.txt

Two files:
    python evaluation/extract_character_outputs.py \
      --baseline outputs/baseline/olaf_retells_red_riding_hood_medium/run_1.json \
      --director outputs/director_agent/olaf_retells_red_riding_hood_medium/run_1.json \
      --out evaluation/results/olaf_retells_red_riding_hood_medium/run_1_character_outputs.txt
"""

import os
import json
import argparse


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_character_lines(transcript: list, label: str) -> str:
    lines = [f"=== {label} ===", ""]

    for i, turn in enumerate(transcript, start=1):
        beat = turn.get("beat", "unknown_beat")
        user_input = turn.get("user_input", "[No user input found]")

        if "model_output" in turn:
            response = turn["model_output"].get("character_response", "")
        elif "actor_output" in turn:
            response = turn["actor_output"].get("character_response", "")
        else:
            response = "[No character output found]"

        lines.append(f"[Turn {i} | Beat: {beat}]")
        lines.append(f"User: {user_input}")
        lines.append(f"Character: {response}")
        lines.append("")

    return "\n".join(lines).strip()


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--input",
        help="Single transcript JSON file to extract character outputs from.",
    )

    parser.add_argument(
        "--baseline",
        help="Baseline transcript JSON file.",
    )

    parser.add_argument(
        "--director",
        help="Director-agent transcript JSON file.",
    )

    parser.add_argument(
        "--out",
        required=True,
        help="Output text file path.",
    )

    args = parser.parse_args()

    single_mode = args.input is not None
    pair_mode = args.baseline is not None and args.director is not None

    if not single_mode and not pair_mode:
        raise ValueError(
            "Provide either --input for single-file mode, or both --baseline and --director for two-file mode."
        )

    if single_mode and (args.baseline or args.director):
        raise ValueError(
            "Do not mix --input with --baseline/--director."
        )

    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    sections = []

    if single_mode:
        transcript = load_json(args.input)

        label = "TRANSCRIPT"
        lower_path = args.input.lower()
        if "baseline" in lower_path:
            label = "BASELINE"
        elif "director" in lower_path:
            label = "DIRECTOR_AGENT"

        sections.append(extract_character_lines(transcript, label))

    else:
        baseline_transcript = load_json(args.baseline)
        director_transcript = load_json(args.director)

        sections.append(extract_character_lines(baseline_transcript, "BASELINE"))
        sections.append(extract_character_lines(director_transcript, "DIRECTOR_AGENT"))

    output_text = "\n\n".join(sections).strip() + "\n"

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(output_text)

    print(f"Saved character outputs to: {args.out}")


if __name__ == "__main__":
    main()