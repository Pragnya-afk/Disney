"""
Implementation/run_codi_interactive.py

Run CoDi's generation pipeline with the interactive user inputs from our
olaf_derailment_scenario_suite.  Each scenario is converted to a CoDi-compatible
JSONL file (with `user_inputs` injected), then generation.py is invoked.

The modified generation.py appends each user input to story_progress after every
main story step, so CoDi's director sees and reacts to the actual user messages.

Outputs land in:
  CoDi-main/CoDi-main/outputs/suite_interactive/<scenario_name>/
    gen_d_gpt-4o_c_gpt-4o.json   — raw CoDi generation output

Usage (from Disney/):
    python Implementation/run_codi_interactive.py
    python Implementation/run_codi_interactive.py --scenarios olaf_first_summer_picnic_no_derailment
    python Implementation/run_codi_interactive.py --dry-run     # print JSONL, don't run
"""

import os
import sys
import json
import argparse
import subprocess
import tempfile

IMPL_DIR = os.path.dirname(__file__)
DISNEY_DIR = os.path.dirname(IMPL_DIR)
CODI_DIR = os.path.join(DISNEY_DIR, "CoDi-main", "CoDi-main")

sys.path.insert(0, IMPL_DIR)
from scenarios.olaf_derailment_scenario_suite import SCENARIOS


def build_codi_inputs(scenario: dict) -> str:
    """Convert a scenario dict to a natural-language CoDi `inputs` paragraph."""
    derailment_level = scenario.get("derailment_level", "none")
    story_topic = scenario["story_topic"]
    beats = scenario["beats"]

    beat_desc = "; ".join(f"{b['name']}: {b['goal']}" for b in beats)

    if derailment_level == "none":
        user_behavior = (
            "The user is engaged and supportive throughout, asking on-topic questions "
            "that help move the story forward."
        )
    elif derailment_level == "medium":
        user_behavior = (
            "About half of the user's questions are completely off-topic and unrelated "
            "to the story. Olaf should acknowledge them briefly but steer back toward "
            "the narrative."
        )
    else:  # complete
        user_behavior = (
            "All of the user's questions are completely off-topic and unrelated to the "
            "story. Olaf should still try to guide the interaction toward a coherent, "
            "complete story despite the persistent interruptions."
        )

    return (
        "Olaf, the friendly snowman from Frozen, narrates this story in his warm, "
        "playful, and enthusiastic voice. He often connects events to themes of warmth, "
        f"love, and the joy of new experiences. {story_topic} "
        f"The story should naturally develop through these narrative moments: {beat_desc}. "
        f"{user_behavior}"
    )


def build_jsonl_record(scenario_name: str, scenario: dict) -> dict:
    return {
        "example_id": scenario_name,
        "inputs": build_codi_inputs(scenario),
        "user_inputs": [u.replace("  # derailment", "").strip() for u in scenario["user_inputs"]],
    }


def run_scenario(scenario_name: str, scenario: dict, out_base_dir: str, model: str, dry_run: bool):
    record = build_jsonl_record(scenario_name, scenario)

    out_dir = os.path.join(out_base_dir, scenario_name)
    out_file = os.path.join(out_dir, f"gen_d_{model}_c_{model}.json")

    # Check if already fully complete (both generation and edit finished)
    if os.path.exists(out_file):
        with open(out_file) as f:
            existing = json.load(f)
        existing_list = existing if isinstance(existing, list) else [existing]
        if any(d.get("example_id") == scenario_name and d.get("edit_state") == "finished" for d in existing_list):
            print(f"[SKIP] Already done: {scenario_name}")
            return

    if dry_run:
        print(f"\n[DRY-RUN] {scenario_name}")
        print(json.dumps(record, indent=2, ensure_ascii=False))
        return

    os.makedirs(out_dir, exist_ok=True)

    # Write JSONL to a temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as f:
        json.dump(record, f, ensure_ascii=False)
        f.write("\n")
        jsonl_path = f.name

    env = os.environ.copy()
    env["LOG_DIR"] = os.path.join(CODI_DIR, "log")
    env["OPENAI_API_KEY"] = env.get(
        "OPENAI_API_KEY",
        "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",
    )

    # CoDi venv python
    python = os.path.join(CODI_DIR, "venv", "bin", "python3")
    if not os.path.exists(python):
        python = sys.executable  # fallback

    cmd = [
        python,
        os.path.join(CODI_DIR, "generation.py"),
        "--data-file", jsonl_path,
        "--out-dir", out_dir,
        "--max-turn", "40",
        "--planner-agent-base-model", model,
        "--director-agent-base-model", model,
        "--character-agent-base-model", model,
        "--editor-agent-base-model", model,
    ]
    # Resume from partial output if generation already completed
    if os.path.exists(out_file):
        cmd += ["--load-file", out_file]

    print(f"\n[RUN] {scenario_name}")
    print(f"  user_inputs: {len(record['user_inputs'])} turns")
    print(f"  out: {out_file}")

    result = subprocess.run(cmd, cwd=CODI_DIR, env=env, capture_output=False)

    os.unlink(jsonl_path)

    if result.returncode != 0:
        print(f"  [ERROR] generation.py exited with code {result.returncode}")
    elif os.path.exists(out_file):
        print(f"  [DONE] saved to {out_file}")
    else:
        print(f"  [WARNING] generation.py finished but output not found at {out_file}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", nargs="*", default=None)
    parser.add_argument("--model", default="gpt-4o")
    parser.add_argument(
        "--out-dir",
        default=os.path.join(CODI_DIR, "outputs", "suite_interactive"),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    all_scenarios = list(SCENARIOS.keys())
    targets = args.scenarios if args.scenarios else all_scenarios

    for scenario_name in targets:
        if scenario_name not in SCENARIOS:
            print(f"[SKIP] Unknown scenario: {scenario_name}")
            continue
        run_scenario(
            scenario_name=scenario_name,
            scenario=SCENARIOS[scenario_name],
            out_base_dir=args.out_dir,
            model=args.model,
            dry_run=args.dry_run,
        )

    print("\nAll done.")


if __name__ == "__main__":
    main()
