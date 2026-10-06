import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

HERE = os.path.dirname(__file__)
PLOTS_DIR = os.path.join(HERE, "plots")
os.makedirs(PLOTS_DIR, exist_ok=True)

phases = pd.read_csv(os.path.join(HERE, "phases.csv"))
participants = pd.read_csv(os.path.join(HERE, "participants.csv"))
participants = participants[participants["n_phases_reached"] > 0].copy()

COND_COLORS = {"director": "#4C72B0", "baseline": "#DD8452", "time_constrained": "#55A868"}

completers = set(participants.loc[participants["dropout_stage"] == "completed", "participant_id"])
comp = phases[phases["participant_id"].isin(completers)]

measures = [
    ("q1_coherence", "Story Coherence"),
    ("q2_in_character", "Maintained Character"),
    ("q4_engagement", "Engaging / Enjoyable"),
    ("q5_overall", "Overall Rating"),
    ("q6_resist_stayed_on_track", "Resistance to Derailment"),
]


COND_LABELS = {"baseline": "baseline", "director": "director", "time_constrained": "time-constrained"}


def make_story_plot(story_num, story_label, cond_a, cond_b, out_name, base_ylim=5.6, show_n_diff=True):
    s = comp[comp["story"] == story_num]
    conds = [cond_a, cond_b]
    legend_handles = [Patch(facecolor=COND_COLORS[c], label=COND_LABELS[c]) for c in conds]
    fig, axes = plt.subplots(2, 3, figsize=(16, 10.5))
    axes = axes.flatten()
    for ax, (col, title) in zip(axes, measures):
        tops = []
        for i, c in enumerate(conds):
            v = s.loc[s["condition"] == c, col].dropna()
            m, sd = (v.mean(), v.std()) if len(v) > 1 else (v.mean() if len(v) else np.nan, 0)
            ax.bar(i, m, yerr=sd, capsize=5, color=COND_COLORS[c])
            if not np.isnan(m):
                if show_n_diff and len(v) != len(completers):
                    label = f"{m:.2f} +/- {sd:.2f} (n={len(v)})"
                else:
                    label = f"{m:.2f} +/- {sd:.2f}"
                ax.text(i, m + sd + 0.08, label, ha="center", fontsize=10, fontweight="bold")
                tops.append(m + sd)
        ax.set_xticks([])
        ax.set_xlim(-0.7, 1.7)
        # Give each subplot just enough headroom for its own tallest error bar +
        # annotation, rather than one fixed limit that's too tight for outliers
        # (e.g. Resistance to Derailment's unusually large error bars) and
        # needlessly loose everywhere else.
        ax.set_ylim(0, max(base_ylim, max(tops, default=0) + 0.6))
        ax.set_title(title, fontsize=16, fontweight="bold")
        ax.set_ylabel("Rating (mean +/- SD)", fontsize=12)
        ax.tick_params(axis="y", labelsize=11)
    legend_ax = axes[5]
    legend_ax.axis("off")
    legend_ax.legend(handles=legend_handles, loc="center", fontsize=16, frameon=False,
                      title="Condition", title_fontsize=17)
    fig.suptitle(f"{story_label} -- questionnaire outcomes, {cond_a} vs {cond_b} (completers, n={len(completers)})",
                 fontsize=16, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(os.path.join(PLOTS_DIR, out_name), dpi=150)
    plt.close(fig)


make_story_plot(1, "Story 1: Frozen", "director", "baseline", "13_story1_all_measures.png")
make_story_plot(2, "Story 2: Cinderella", "director", "time_constrained", "15_story2_all_measures.png", show_n_diff=False)

print("Wrote 13_story1_all_measures.png and 15_story2_all_measures.png to", PLOTS_DIR)
