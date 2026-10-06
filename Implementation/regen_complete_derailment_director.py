"""
regen_complete_derailment_director.py

One-off script: regenerate the director_agent transcripts for the 10
complete-derailment scenarios (of the 33-scenario baseline-vs-director set)
that were diagnosed as stuck looping on beat 1, now that director_core.py's
pacing_instruction_suffix fix is in place. Overwrites outputs/director_agent/
<name>/batch/run_1.json for each -- the pre-fix versions were already backed
up to run_1_prefix.json.

Usage (from Implementation/):
    python regen_complete_derailment_director.py
"""

import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CURRENT_DIR))
sys.path.insert(0, str(CURRENT_DIR / "director_agent"))

from dotenv import load_dotenv
load_dotenv(str(CURRENT_DIR / ".env"))

from director_agent.auto_main import run_story

NAMES = [
    "olaf_arendelle_tour_complete_derailment",
    "olaf_first_summer_picnic_complete_derailment",
    "olaf_frozen_adventure_traditions_complete_derailment",
    "olaf_lost_lantern_adventure_complete_derailment",
    "olaf_lost_snowflake_complete_derailment",
    "olaf_makes_anna_smile_complete_derailment",
    "olaf_once_upon_a_snowman_origin_complete_derailment",
    "olaf_presents_ocean_adventure_complete_derailment",
    "olaf_retells_red_riding_hood_complete_derailment",
    "olaf_winter_festival_surprise_complete_derailment",
]

CHARACTER_MODULE = "character_prompts.olaf"
SCENARIO_MODULE = "scenarios.olaf_derailment_scenario_suite"


def main():
    for i, name in enumerate(NAMES, 1):
        print(f"\n[{i}/{len(NAMES)}] {name}")
        try:
            path = run_story(
                character_module=CHARACTER_MODULE,
                scenario_module=SCENARIO_MODULE,
                run_id=1,
                scenario_name_override=name,
            )
            print(f"  saved: {path}")
        except Exception as e:
            print(f"  ERROR: {e}")


if __name__ == "__main__":
    main()
