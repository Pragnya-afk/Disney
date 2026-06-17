"""
evaluation_agent/extract_character_outputs.py

Extract readable character-only outputs from transcript JSON files.

Supports:
1. One file only:
   --input ...
2. Two files (baseline vs director):
   --baseline ... --director ...
3. Director vs CoDi — two variants:
   a. --director ... --codi ...          (pre-converted transcript format)
   b. --director ... --codi-raw ...      (original CoDi-main JSON with narrative/direct_response)

The --codi-raw flag reads the original CoDi output format from CoDi-main/outputs/suite/,
preserving the CoDi director's reasoning and multi-turn story progress.

Example
--------
Single file:
        python evaluation_agent/extract_character_outputs.py \
            --input outputs/baseline/olaf_retells_red_riding_hood_medium/run_1.json \
            --out evaluation_results/olaf_retells_red_riding_hood_medium/run_1_baseline_character_outputs.txt

Baseline vs director:
        python evaluation_agent/extract_character_outputs.py \
            --baseline outputs/baseline/olaf_retells_red_riding_hood_medium/run_1.json \
            --director outputs/director_agent/olaf_retells_red_riding_hood_medium/run_1.json \
            --out evaluation_results/olaf_retells_red_riding_hood_medium/run_1_character_outputs.txt

Director vs CoDi (original CoDi-main format):
        python evaluation_agent/extract_character_outputs.py \
            --director outputs/director_agent/olaf_arendelle_tour_no_derailment/batch/run_1.json \
            --codi-raw ../../CoDi-main/CoDi-main/outputs/suite/olaf_arendelle_tour_no_derailment/gen_d_gpt-4o_c_gpt-4o.json \
            --out evaluation_results/olaf_arendelle_tour_no_derailment/character_outputs.txt
"""

import os
import re
import json
import argparse


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_character_lines(transcript: list, label: str) -> str:
    """Extract from standard transcript format (baseline / director / pre-converted codi)."""
    lines = [f"=== {label} ===", ""]

    for i, turn in enumerate(transcript, start=1):
        beat = turn.get("beat", "unknown_beat")
        user_input = turn.get("user_input", "")

        if "actor_output" in turn:
            response = turn["actor_output"].get("character_response", "")
            dd = turn.get("director_decision", {})
            director_instr = dd.get("director_instruction", "")
            lines.append(f"[Turn {i} | Beat: {beat}]")
            if user_input:
                lines.append(f"User:     {user_input}")
            if director_instr:
                lines.append(f"Director: {director_instr}")
            lines.append(f"Character: {response}")
        elif "model_output" in turn:
            response = turn["model_output"].get("character_response", "")
            lines.append(f"[Turn {i} | Beat: {beat}]")
            if user_input:
                lines.append(f"User:     {user_input}")
            lines.append(f"Character: {response}")
        else:
            lines.append(f"[Turn {i} | Beat: {beat}]")
            lines.append("[No character output found]")

        lines.append("")

    return "\n".join(lines).strip()


def _parse_codi_director_reason(direct_response: str) -> str:
    """Pull out the Reason + Choice/Description from CoDi's direct_response."""
    if not direct_response:
        return ""
    reason = re.search(r"Reason:\s*(.+?)(?=Choice:|Description:|Pass|$)", direct_response, re.DOTALL)
    choice = re.search(r"(?:Choice|Description):\s*(.+?)$", direct_response, re.DOTALL | re.IGNORECASE)
    parts = []
    if reason:
        parts.append("Reason: " + reason.group(1).strip())
    if choice:
        parts.append(choice.group(0).strip())
    return "\n".join(parts)


def extract_codi_raw_lines(codi_json_path: str, label: str = "CODI") -> str:
    """
    Extract from the original CoDi-main output format.

    Each turn has:
      direct_response — CoDi director's reasoning + action choice
      story_progress  — actual narrative / character output
    """
    data = load_json(codi_json_path)
    if isinstance(data, list):
        data = data[0]

    narrative = data.get("narrative", {})

    # Sort turns numerically, skip turn_-1 and entries whose story_progress is "STORY ENDS"
    turn_keys = sorted(
        (k for k in narrative if k.startswith("turn_") and k != "turn_-1"),
        key=lambda k: int(re.search(r"-?\d+", k).group()),
    )

    lines = [f"=== {label} ===", ""]
    lines.append("NOTE: CoDi generates its story autonomously — no live user inputs.")
    lines.append("      The CoDi director decides what happens each turn internally.")
    lines.append("")

    for i, key in enumerate(turn_keys, start=1):
        turn = narrative[key]
        story_progress = turn.get("story_progress", "").strip()
        direct_response = turn.get("direct_response", "").strip()

        if re.match(r"^(PART|ACT|STORY)\s*\d*\s*ENDS$", story_progress, re.IGNORECASE):
            lines.append(f"[Turn {i} | {key}]")
            lines.append("--- STORY ENDS ---")
            lines.append("")
            continue

        director_summary = _parse_codi_director_reason(direct_response)

        lines.append(f"[Turn {i} | {key}]")
        if director_summary:
            lines.append(f"CoDi Director: {director_summary}")
        lines.append(f"Story Output:  {story_progress}")
        lines.append("")

    return "\n".join(lines).strip()


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--input", help="Single transcript JSON file.")
    parser.add_argument("--baseline", help="Baseline transcript JSON file.")
    parser.add_argument("--director", help="Director-agent transcript JSON file.")
    parser.add_argument("--codi", help="Pre-converted CoDi transcript JSON file.")
    parser.add_argument(
        "--codi-raw",
        dest="codi_raw",
        help="Original CoDi-main JSON file (narrative/direct_response format).",
    )
    parser.add_argument("--out", required=True, help="Output text file path.")

    args = parser.parse_args()

    single_mode = args.input is not None
    baseline_director_mode = args.baseline is not None and args.director is not None
    director_codi_mode = (
        args.director is not None
        and (args.codi is not None or args.codi_raw is not None)
        and args.baseline is None
    )

    if not single_mode and not baseline_director_mode and not director_codi_mode:
        raise ValueError(
            "Provide either --input, or --baseline + --director, "
            "or --director + --codi / --codi-raw."
        )

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    sections = []

    if single_mode:
        transcript = load_json(args.input)
        lower = args.input.lower()
        label = "CODI" if "codi" in lower else "DIRECTOR_AGENT" if "director" in lower else "BASELINE"
        sections.append(extract_character_lines(transcript, label))

    elif baseline_director_mode:
        sections.append(extract_character_lines(load_json(args.baseline), "BASELINE"))
        sections.append(extract_character_lines(load_json(args.director), "DIRECTOR_AGENT"))

    else:  # director_codi_mode
        sections.append(extract_character_lines(load_json(args.director), "DIRECTOR_AGENT"))
        if args.codi_raw:
            sections.append(extract_codi_raw_lines(args.codi_raw, "CODI"))
        else:
            sections.append(extract_character_lines(load_json(args.codi), "CODI"))

    output_text = "\n\n".join(sections).strip() + "\n"

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(output_text)

    print(f"Saved character outputs to: {args.out}")


if __name__ == "__main__":
    main()
