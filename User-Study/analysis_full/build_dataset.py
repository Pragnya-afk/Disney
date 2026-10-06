"""
Build a tidy dataset from User-Study/outputs_all/phase_*/*.json (the current,
canonical set of session files).

Supersedes analysis/build_dataset.py, which pointed at User-Study/outputs_disney
and User-Study/outputs_gtc -- directories that no longer exist on disk. That
script's output (analysis/participants.csv, phases.csv) is a stale snapshot
from 2026-09-01 covering sessions only through 2026-08-10; outputs_all now
holds sessions through 2026-08-26.

This script also fixes a bug present in analysis_2's by-hand tabulation:
outputs_all contains two files for the same participant id ("TxUvTJNR") --
an abandoned first attempt and a restarted, more-complete second attempt.
Both live in outputs_all (in different phase_N folders) because the reorg
that produced outputs_all did not dedupe restarts. Analysis_2 counted both
as separate participants (once as a Phase-1 abandoner, once as a Phase-3
abandoner). Here, as in the original analysis/build_dataset.py, only the
latest-timestamped file per participant id is kept.

Produces phases.csv and participants.csv in User-Study/analysis_full/.
"""

import json
import glob
import os
import re
import sys
from collections import defaultdict

import pandas as pd

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "Implementation"))
from scenarios.olaf_derailment_scenario_suite import SCENARIOS  # noqa: E402

OUT_DIR = os.path.dirname(__file__)
SRC_GLOB = os.path.join(REPO_ROOT, "User-Study", "outputs_all", "phase_*", "*.json")
FNAME_RE = re.compile(r"session_(\d{8})_(\d{6})_(.+)\.json$")


def total_beats(scenario_name):
    sc = SCENARIOS.get(scenario_name)
    return len(sc["beats"]) if sc else None


def load_latest_per_participant():
    groups = defaultdict(list)
    for fp in sorted(glob.glob(SRC_GLOB)):
        base = os.path.basename(fp)
        m = FNAME_RE.match(base)
        if not m:
            continue
        date, time, pid = m.groups()
        groups[pid].append((date + time, fp))

    latest = {}
    n_restarts = {}
    for pid, items in groups.items():
        items.sort()
        latest[pid] = items[-1][1]
        n_restarts[pid] = len(items) - 1
    return latest, n_restarts


def main():
    latest, n_restarts = load_latest_per_participant()

    phase_rows = []
    participant_rows = []

    for pid, fp in sorted(latest.items()):
        with open(fp, encoding="utf-8") as f:
            d = json.load(f)

        phases = d.get("phases", {})
        if not phases:
            participant_rows.append(
                {
                    "participant_id": pid,
                    "study_date": d.get("study_date"),
                    "first_condition": None,
                    "n_phases_reached": 0,
                    "abandoned_at_phase": None,
                    "dropout_stage": "never_started",
                    "n_restarts": n_restarts[pid],
                }
            )
            continue

        story1_order = d.get("story1_order") or [None, None]
        story2_order = d.get("story2_order") or [None, None]
        abandoned_at = d.get("abandoned_at_phase")

        for phase_num_str, p in phases.items():
            phase_num = int(phase_num_str)
            story = p.get("story")
            order_list = story1_order if story == 1 else story2_order
            cond = p.get("condition")
            order_position = (order_list.index(cond) + 1) if cond in order_list else None

            scen = p.get("scenario", "")
            tot_beats = total_beats(scen)
            beats_completed = p.get("beats_completed", 0)

            q = p.get("questionnaire", {}) or {}
            elapsed = p.get("elapsed_seconds", 0) or 0
            limit_s = (p.get("time_limit_minutes") or 0) * 60
            finished_story = (tot_beats is not None and beats_completed >= tot_beats) or (
                cond == "time_constrained" and limit_s and elapsed >= limit_s * 0.95
            )

            phase_rows.append(
                {
                    "participant_id": pid,
                    "study_date": d.get("study_date"),
                    "phase": phase_num,
                    "story": story,
                    "round": p.get("round"),
                    "condition": cond,
                    "order_position": order_position,
                    "scenario": scen,
                    "beats_completed": beats_completed,
                    "total_beats": tot_beats,
                    "completion_ratio": (beats_completed / tot_beats) if tot_beats else None,
                    "elapsed_seconds": elapsed,
                    "time_limit_seconds": limit_s,
                    "n_turns": len(p.get("turns", []) or []),
                    "finished_story": finished_story,
                    "has_questionnaire": bool(q),
                    "q1_coherence": q.get("q1"),
                    "q2_in_character": q.get("q2"),
                    "q4_engagement": q.get("q4"),
                    "q5_overall": q.get("q5"),
                    "q6_tried_derail": q.get("q6"),
                    "q6_resist_stayed_on_track": q.get("q6_resist"),
                    "q_pacing": q.get("q_pacing"),
                    "q8_ending_satisfying": q.get("q8_ending"),
                    "q8_knows_story": q.get("q8_knows_story"),
                    "q10_natural": q.get("q10_natural"),
                    "q_breakdown_text": q.get("q_breakdown"),
                    "q_comments_text": q.get("q_comments"),
                }
            )

        first_cond = story1_order[0] if story1_order else None
        last_phase_data = phases.get(str(int(abandoned_at))) if abandoned_at is not None else None

        # "Completed" = actually finished phase 4 with a submitted questionnaire.
        # NOTE: this differs from the earlier analysis/build_dataset.py, which
        # defined completion as abandoned_at_phase being null (i.e. the socket
        # never once disconnected/reconnected the whole session). That metric
        # returned 0/29 "completed" even for participants who plainly finished
        # every phase and every questionnaire, because a disconnect/reconnect
        # blip anywhere in the session (a refresh, a network hiccup) still sets
        # abandoned_at_phase. Completion via "phase 4 has a submitted
        # questionnaire" is the metric that matches what a reader means by
        # "finished the study."
        phase4 = phases.get("4")
        reached_and_finished_p4 = bool(phase4 and phase4.get("questionnaire"))

        if reached_and_finished_p4:
            dropout_stage = "completed"
        elif last_phase_data is None:
            dropout_stage = f"phase_{int(abandoned_at)}_zero_engagement"
        else:
            last_scen = last_phase_data.get("scenario", "")
            last_tot = total_beats(last_scen)
            last_beats = last_phase_data.get("beats_completed", 0)
            last_elapsed = last_phase_data.get("elapsed_seconds", 0) or 0
            last_limit = (last_phase_data.get("time_limit_minutes") or 0) * 60
            story_was_finished = (last_tot is not None and last_beats >= last_tot) or (
                last_limit and last_elapsed >= last_limit * 0.95
            )
            if story_was_finished:
                dropout_stage = f"phase_{int(abandoned_at)}_after_story_before_questionnaire"
            else:
                dropout_stage = f"phase_{int(abandoned_at)}_mid_story"

        participant_rows.append(
            {
                "participant_id": pid,
                "study_date": d.get("study_date"),
                "story1_order": story1_order,
                "story2_order": story2_order,
                "first_condition": first_cond,
                "n_phases_reached": len(phases),
                "abandoned_at_phase": abandoned_at,
                "completed_study": reached_and_finished_p4,
                "dropout_stage": dropout_stage,
                "n_restarts": n_restarts[pid],
            }
        )

    phases_df = pd.DataFrame(phase_rows)
    participants_df = pd.DataFrame(participant_rows)

    phases_df.to_csv(os.path.join(OUT_DIR, "phases.csv"), index=False)
    participants_df.to_csv(os.path.join(OUT_DIR, "participants.csv"), index=False)

    print(f"Wrote {len(phases_df)} phase-rows, {len(participants_df)} participant-rows")
    print(participants_df["dropout_stage"].value_counts())


if __name__ == "__main__":
    main()
