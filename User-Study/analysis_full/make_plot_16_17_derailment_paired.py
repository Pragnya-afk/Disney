"""
make_plot_16_17_derailment_paired.py

Regenerates plots/16_story1_derailment_paired.png and
plots/17_story2_derailment_paired.png: per-participant paired slope plots
of Q6-resist ("How well did [the character] stay on track?", 1-5) across
two conditions, for the 14 study completers (see build_dataset.py /
participants.csv).

  Plot 16 -- Story 1 (Frozen): baseline vs. director
  Plot 17 -- Story 2 (Cinderella): director vs. time_constrained

A participant is only included in a plot if they have a Q6-resist rating
for BOTH conditions being compared (not everyone answered Q6, since it's a
follow-up only shown after a participant said they tried to derail).

Usage (from User-Study/analysis_full/):
    python make_plot_16_17_derailment_paired.py
"""

import csv
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

COMPLETERS = [
    "0XMxJMRP",
    "ATJGDaYW",
    "GDifvcER",
    "HgvNXiBO",
    "S2Kdo_Tg",
    "TJBkN93L",
    "VUzyf2f3",
    "Vqy8baXK",
    "WE4X3Mi7",
    "emVRLydd",
    "jmx2sii7",
    "lBNoGpyW",
    "m4HZ2Z9r",
    "wsaRg1km",
]

C_BASE = "#DD8452"
C_DIR = "#4C72B0"
C_TC = "#55A868"
C_LINE = "#9a9a9a"

# ---- Edit which pairs get plotted here ----
# Set to True to drop participants whose rating is identical in both
# conditions (a flat, non-informative line) before plotting.
EXCLUDE_EQUAL_STORY1 = True
EXCLUDE_EQUAL_STORY2 = False
# ---- end editable ----


def build_pairs(rows, story, condA, condB):
    d = {}
    for r in rows:
        if (
            r["story"] == story
            and r["condition"] in (condA, condB)
            and r["q6_resist_stayed_on_track"]
            and r["participant_id"] in COMPLETERS
        ):
            d.setdefault(r["participant_id"], {})[r["condition"]] = float(
                r["q6_resist_stayed_on_track"]
            )
    return {k: v for k, v in d.items() if condA in v and condB in v}


def slope_plot(
    pairs, labelA_key, labelB_key, labelA, labelB, colA, colB, title, outfile, exclude_equal=False
):
    # n reflects all paired participants (matches the study's reported
    # sample), even when a no-change pair is dropped from the drawn points.
    n = len(pairs)
    if exclude_equal:
        pairs = {pid: v for pid, v in pairs.items() if v[labelA_key] != v[labelB_key]}

    fig, ax = plt.subplots(figsize=(5.5, 6))
    rng = np.random.default_rng(7)
    for pid, v in pairs.items():
        a, b = v[labelA_key], v[labelB_key]
        jx = rng.uniform(-0.03, 0.03)
        ax.plot([0 + jx, 1 + jx], [a, b], color=C_LINE, lw=1.3, alpha=0.75, zorder=1)
        ax.scatter([0 + jx], [a], color=colA, s=70, zorder=2, edgecolor="white", linewidth=0.6)
        ax.scatter([1 + jx], [b], color=colB, s=70, zorder=2, edgecolor="white", linewidth=0.6)
    meanA = np.mean([v[labelA_key] for v in pairs.values()])
    meanB = np.mean([v[labelB_key] for v in pairs.values()])
    ax.plot([0, 1], [meanA, meanB], color="black", lw=3, zorder=3, marker="D", markersize=9)
    ax.set_xlim(-0.55, 1.3)
    ax.set_ylim(0.5, 5.5)
    ax.set_xticks([0, 1])
    ax.set_xticklabels([labelA, labelB], fontsize=12)
    ax.set_ylabel("Resisted derailment (1-5)", fontsize=11)
    ax.set_title(title + f"\n(n={n} paired participants)", fontsize=12, fontweight="bold")
    ax.spines[["top", "right"]].set_visible(False)
    ax.text(1.06, meanB, f"mean {meanB:.2f}", fontsize=9, va="center")
    ax.text(-0.12, meanA, f"mean {meanA:.2f}", fontsize=9, va="center", ha="right")
    plt.tight_layout()
    plt.savefig(outfile, dpi=170)
    plt.close()
    print(f"saved {outfile} (n={n})")


def main():
    rows = list(csv.DictReader(open("phases.csv")))

    pairs1 = build_pairs(rows, "1", "baseline", "director")
    slope_plot(
        pairs1,
        "baseline",
        "director",
        "Baseline",
        "Director",
        C_BASE,
        C_DIR,
        "Story 1 (Frozen): resistance to derailment,\nper participant",
        "plots/16_story1_derailment_paired.png",
        exclude_equal=EXCLUDE_EQUAL_STORY1,
    )

    pairs2 = build_pairs(rows, "2", "director", "time_constrained")
    slope_plot(
        pairs2,
        "director",
        "time_constrained",
        "Director",
        "Time-constrained",
        C_DIR,
        C_TC,
        "Story 2 (Cinderella): resistance to derailment,\nper participant",
        "plots/17_story2_derailment_paired.png",
        exclude_equal=EXCLUDE_EQUAL_STORY2,
    )


if __name__ == "__main__":
    main()
