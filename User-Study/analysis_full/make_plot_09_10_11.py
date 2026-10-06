"""
make_plot_09_10_11.py

Reconstructs three plots that existed as static images with no generator
script in the repo:
    09_derailment_story_comparison.png
    10_story2_pacing_by_condition.png
    11_story2_ending_and_naturalness.png

Values were verified against the existing images before writing this script
(same means, SDs, and counts). Rebuilt here mainly to drop "n=" annotations
that were redundant with the completers total stated in each figure's title
(09's counts genuinely vary per bar and are kept; 10 and 11's were constant
at n=14 everywhere and are dropped).

Usage (from Implementation/analysis_full, i.e. this directory):
    python make_plot_09_10_11.py
"""

import os
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(__file__)
PLOTS_DIR = os.path.join(HERE, "plots")
os.makedirs(PLOTS_DIR, exist_ok=True)

phases = pd.read_csv(os.path.join(HERE, "phases.csv"))
participants = pd.read_csv(os.path.join(HERE, "participants.csv"))
participants = participants[participants["n_phases_reached"] > 0].copy()

COND_COLORS = {"director": "#4C72B0", "baseline": "#DD8452", "time_constrained": "#55A868"}

completers = set(participants.loc[participants["dropout_stage"] == "completed", "participant_id"])
comp = phases[phases["participant_id"].isin(completers)]

# --- Plot 9: resistance to derailment by story and condition ---
fig, axes = plt.subplots(1, 2, figsize=(11, 5))

s1 = comp[comp["story"] == 1]
ax = axes[0]
for i, c in enumerate(["director", "baseline"]):
    v = s1.loc[s1["condition"] == c, "q6_resist_stayed_on_track"].dropna()
    m, sd = v.mean(), v.std()
    ax.bar(i, m, yerr=sd, capsize=5, color=COND_COLORS[c])
    ax.text(
        i,
        m + sd + 0.12,
        f"{m:.2f} +/- {sd:.2f} (n={len(v)})",
        ha="center",
        fontsize=10,
        fontweight="bold",
    )
ax.set_xticks([0, 1])
ax.set_xticklabels(["director", "baseline"])
ax.set_ylim(0, 6.3)
ax.set_title("Story 1: Frozen", fontweight="bold")
ax.set_ylabel("Resisted Derailment Rating")

s2 = comp[comp["story"] == 2]
ax = axes[1]
for i, c in enumerate(["director", "time_constrained"]):
    v = s2.loc[s2["condition"] == c, "q6_resist_stayed_on_track"].dropna()
    m, sd = v.mean(), v.std()
    ax.bar(i, m, yerr=sd, capsize=5, color=COND_COLORS[c])
    ax.text(
        i,
        m + sd + 0.12,
        f"{m:.2f} +/- {sd:.2f} (n={len(v)})",
        ha="center",
        fontsize=10,
        fontweight="bold",
    )
ax.set_xticks([0, 1])
ax.set_xticklabels(["director", "time_constrained"])
ax.set_ylim(0, 6.3)
ax.set_title("Story 2: Cinderella", fontweight="bold")

fig.suptitle(
    f"Resistance to Derailment by Story and Condition (Complete Participants, n={len(completers)})",
    fontsize=13,
    fontweight="bold",
)
fig.tight_layout(rect=[0, 0, 1, 0.93])
fig.savefig(os.path.join(PLOTS_DIR, "09_derailment_story_comparison.png"), dpi=150)
plt.close(fig)

# --- Plot 10: story 2 pacing verdict by condition ---
PACING_COLORS = {"well-paced": "#2ca02c", "rushed": "#ff9800", "cut-short": "#d62728"}
PACING_ORDER = ["well-paced", "rushed", "cut-short"]

fig, ax = plt.subplots(figsize=(6.5, 5.5))
conds = ["director", "time_constrained"]
bottoms = [0, 0]
for verdict in PACING_ORDER:
    vals = []
    for c in conds:
        v = s2.loc[s2["condition"] == c, "q_pacing"]
        vals.append((v == verdict).sum())
    bars = ax.bar(conds, vals, bottom=bottoms, color=PACING_COLORS[verdict], label=verdict)
    for rect, val in zip(bars, vals):
        if val > 0:
            ax.text(
                rect.get_x() + rect.get_width() / 2,
                rect.get_y() + val / 2,
                str(val),
                ha="center",
                va="center",
                color="white",
                fontsize=12,
                fontweight="bold",
            )
    bottoms = [b + v for b, v in zip(bottoms, vals)]

ax.set_ylim(0, 16)
ax.set_ylabel("Number of completers (Story 2, n=14 per condition)")
ax.set_title('Story 2 pacing verdict by condition\n("Did the story\'s pacing feel right?")')
ax.legend(loc="upper right", bbox_to_anchor=(1.35, 1.0))
fig.tight_layout()
fig.savefig(os.path.join(PLOTS_DIR, "10_story2_pacing_by_condition.png"), dpi=150)
plt.close(fig)

# --- Plot 11: story 2 ending satisfaction and naturalness ---
fig, axes = plt.subplots(1, 2, figsize=(9, 5.5))

ax = axes[0]
for i, c in enumerate(conds):
    v = s2.loc[s2["condition"] == c, "q8_ending_satisfying"].dropna()
    m, sd = v.mean(), v.std()
    ax.bar(i, m, yerr=sd, capsize=5, color=COND_COLORS[c])
    ax.text(i, m + sd + 0.12, f"{m:.2f} +/- {sd:.2f}", ha="center", fontsize=11, fontweight="bold")
ax.set_xticks([0, 1])
ax.set_xticklabels(conds)
ax.set_ylim(0, 6.3)
ax.set_title("Was the ending satisfying?\n(1=very unsatisfying, 5=very satisfying)")

ax = axes[1]
for i, c in enumerate(conds):
    v = s2.loc[s2["condition"] == c, "q10_natural"].dropna()
    m, sd = v.mean(), v.std()
    ax.bar(i, m, yerr=sd, capsize=5, color=COND_COLORS[c])
    ax.text(i, m + sd + 0.12, f"{m:.2f} +/- {sd:.2f}", ha="center", fontsize=11, fontweight="bold")
ax.set_xticks([0, 1])
ax.set_xticklabels(conds)
ax.set_ylim(0, 6.3)
ax.set_title("Did it feel natural?\n(1=not at all, 5=completely natural)")

fig.suptitle(
    f"Story 2 (Cinderella) ending quality, director vs time_constrained (n={len(completers)} completers)",
    fontsize=13,
    fontweight="bold",
)
fig.tight_layout(rect=[0, 0, 1, 0.90])
fig.savefig(os.path.join(PLOTS_DIR, "11_story2_ending_and_naturalness.png"), dpi=150)
plt.close(fig)

print(
    "Wrote 09_derailment_story_comparison.png, 10_story2_pacing_by_condition.png, "
    "11_story2_ending_and_naturalness.png to",
    PLOTS_DIR,
)
