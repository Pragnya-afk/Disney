import json
import argparse
from pathlib import Path


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_lines(transcript: list, method_name: str) -> list[str]:
    lines = [f"=== {method_name.upper()} ===", ""]

    for turn in transcript:
        turn_index = turn.get("turn_index", "?")
        beat = turn.get("beat", "unknown")

        if "model_output" in turn:
            text = turn["model_output"].get("character_response", "").strip()
        elif "actor_output" in turn:
            text = turn["actor_output"].get("character_response", "").strip()
        else:
            text = ""

        if text:
            lines.append(f"[Turn {turn_index} | Beat: {beat}]")
            lines.append(text)
            lines.append("")

    return lines


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True, help="Path to baseline transcript JSON")
    parser.add_argument("--director", required=True, help="Path to director-agent transcript JSON")
    parser.add_argument("--out", required=True, help="Output text file path")
    args = parser.parse_args()

    baseline = load_json(args.baseline)
    director = load_json(args.director)

    output_lines = []
    output_lines.extend(extract_lines(baseline, "baseline"))
    output_lines.append("")
    output_lines.extend(extract_lines(director, "director_agent"))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(output_lines), encoding="utf-8")

    print(f"Saved extracted character outputs to: {out_path}")


if __name__ == "__main__":
    main()
