"""
make_plot_12_beat_compression.py

Regenerates plots/12_beat_compression_time_constrained.png: for each of the 9
Cinderella beats, how the time_constrained (5-minute) director actually
handled it across the 14 study completers (participants who finished all 4
rounds + the closing questionnaire -- see analysis_full/build_dataset.py).

This reads directly from outputs_all/phase_4/*.json -- every completer's
session file lives there (their 4th and final recorded phase), regardless of
which of their 4 rounds happened to be the time_constrained/story-2 one
(order was randomized per participant, so it's phase 3 or 4 depending on the
person -- the script finds whichever phase has condition == "time_constrained"
inside each file).

Per-beat category, read off each turn's `beat` and `pacing_mode` field:
  developed    -- got its own turn(s), all at normal pacing
  hurried      -- got exactly one turn, and it wasn't tagged normal
                  (pacing nudged but not yet force-compressed)
  compressed   -- got its own turn(s), at least one tagged critical/final
                  (the director was actively compressing it under pressure)
  skipped      -- never got its own turn, and the story's own turns had
                  already moved on to a later beat by the time it ended --
                  i.e. the narrative jumped straight past it mid-story
  folded_final -- never got its own turn, but was still "ahead" of
                  wherever the story's own turns stopped -- i.e. it was
                  swept into the closing turn (or would have been, if the
                  session hadn't ended first -- see the abandoned-session
                  note below)

Two of the 14 completers (emVRLydd, wsaRg1km) stopped sending messages
partway through this round -- with 150-180s still left on the clock -- so
the time-constrained director never got the chance to force-close their
story and fold the remaining beats into an actual closing turn the way it
does for everyone else. Their trailing, never-narrated beats are still
counted as "folded_final" (rather than a separate not-reached category)
since they're the same kind of beat -- left over at the end -- just
without a closing turn to actually fold them into. n=14.

Usage (from User-Study/analysis_full/):
    python make_plot_12_beat_compression.py
"""

import json
import glob
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SCRIPT_DIR = Path(__file__).parent
SESSIONS_DIR = SCRIPT_DIR.parent / "outputs_all" / "phase_4"
OUT_PATH = SCRIPT_DIR / "plots" / "12_beat_compression_time_constrained.png"

BEATS = ['story_opening', 'stepfamily_cruelty', 'royal_invitation', 'fairy_godmother_appears',
         'ball_preparation', 'at_the_ball', 'midnight_escape', 'slipper_search', 'resolution']
BEAT_LABELS = ['1. Story opening', '2. Stepfamily cruelty', '3. Royal invitation',
               '4. Fairy godmother appears', '5. Ball preparation', '6. At the ball',
               '7. Midnight escape', '8. Slipper search', '9. Resolution']
BEAT_RANK = {b: i for i, b in enumerate(BEATS)}
CATS = ['developed', 'hurried', 'compressed', 'skipped', 'folded_final']

# Director-assigned importance per beat, from the scenario definition
# (Implementation/scenarios/olaf_derailment_scenario_suite.py, olaf_retells_cinderella).
# Shown as a small subtitle under each beat label so compression can be read
# against the priority the director was actually told to protect.
BEAT_PRIORITY = {
    'story_opening': 'medium',
    'stepfamily_cruelty': 'low',
    'royal_invitation': 'medium',
    'fairy_godmother_appears': 'high',
    'ball_preparation': 'medium',
    'at_the_ball': 'high',
    'midnight_escape': 'high',
    'slipper_search': 'medium',
    'resolution': 'high',
}

# ---- Edit plot text here ----
TITLE = ("Compression of Cinderella beats under time-constrained pacing (5 mins) \n")
CAT_LABELS = {
    'developed': 'Developed at normal pace',
    'hurried': 'Hurried (finished in 1 turn, no compression forced)',
    'compressed': 'Compressed (critical pacing)',
    'skipped': 'Skipped ahead mid-story',
    'folded_final': 'Folded into closing turn',
}
XLABEL_TEMPLATE = "Number of time_constrained phases (n={n} transcripts)"
# ---- end editable text ----

CAT_COLORS = {
    'developed': '#2E8B2E', 'hurried': '#8FBF3F', 'compressed': '#E8A33D',
    'skipped': '#B22222', 'folded_final': '#6A3D9A',
}


def classify_sessions():
    results = {}
    for f in sorted(glob.glob(str(SESSIONS_DIR / "*.json"))):
        m = re.match(r"session_\d{8}_\d{6}_(.+)\.json", Path(f).name)
        pid = m.group(1)
        d = json.load(open(f))
        tc_phase = None
        for _, p in d["phases"].items():
            if p.get("condition") == "time_constrained":
                tc_phase = p
        if tc_phase is None:
            continue

        turns = tc_phase.get("turns", [])
        beat_turns = {}
        last_beat_rank = -1
        for t in turns:
            b, pm = t.get("beat"), t.get("pacing_mode")
            if b in BEAT_RANK:
                beat_turns.setdefault(b, []).append(pm)
                last_beat_rank = max(last_beat_rank, BEAT_RANK[b])

        cats = {}
        for b in BEATS:
            if b in beat_turns:
                pms = beat_turns[b]
                if any(pm in ("critical", "final") for pm in pms):
                    cats[b] = "compressed"
                elif len(pms) == 1 and pms[0] != "normal":
                    cats[b] = "hurried"
                else:
                    cats[b] = "developed"
            else:
                if BEAT_RANK[b] <= last_beat_rank:
                    cats[b] = "skipped"  # jumped past mid-story
                else:
                    # Trailing beat, never got its own turn: either swept
                    # into an actual closing turn (reached_final), or the
                    # session ended before one could fire -- see module
                    # docstring. Both count as "folded_final".
                    cats[b] = "folded_final"
        results[pid] = cats
    return results


def main():
    results = classify_sessions()
    n = len(results)

    counts = {b: {c: 0 for c in CATS} for b in BEATS}
    for pid, cats in results.items():
        for b in BEATS:
            counts[b][cats[b]] += 1

    print(f"n transcripts: {n}")
    for b in BEATS:
        print(b, counts[b])

    fig, ax = plt.subplots(figsize=(11, 7))
    y = range(len(BEATS))
    left = [0] * len(BEATS)
    for c in CATS:
        vals = [counts[b][c] for b in BEATS]
        ax.barh(list(y), vals, left=left, color=CAT_COLORS[c], label=CAT_LABELS[c])
        for i, v in enumerate(vals):
            if v > 0:
                ax.text(left[i] + v / 2, i, str(v), ha="center", va="center",
                         color="white", fontsize=10, fontweight="bold")
        left = [l + v for l, v in zip(left, vals)]

    ax.set_yticks(list(y))
    ax.set_yticklabels([])  # replaced by the two-line labels drawn below
    ax.invert_yaxis()
    for i, b in enumerate(BEATS):
        ax.text(-0.01, i - 0.16, BEAT_LABELS[i], transform=ax.get_yaxis_transform(),
                 ha="right", va="center", fontsize=11)
        ax.text(-0.01, i + 0.20, f"{BEAT_PRIORITY[b]} priority", transform=ax.get_yaxis_transform(),
                 ha="right", va="center", fontsize=8, color="dimgray", style="italic")
    ax.set_xlabel(XLABEL_TEMPLATE.format(n=n))
    ax.set_xlim(0, n)
    ax.set_title(TITLE)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2, fontsize=9, frameon=True)
    plt.tight_layout()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUT_PATH, dpi=170, bbox_inches="tight")
    print(f"saved {OUT_PATH}")


if __name__ == "__main__":
    main()
