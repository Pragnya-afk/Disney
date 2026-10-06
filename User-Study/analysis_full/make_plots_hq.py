"""High-resolution, deck-styled re-creations of the user-study and case-study plots.

Same data and same computations as User-Study/analysis_full/make_plots.py,
make_plot_09_10_11.py, make_plot_13_15_story_all_measures.py and
Implementation/generate_case_study_plots.py; only the styling changes.
"""

import os
import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from scipy.stats import wilcoxon

DATA = "/home/prachakonda/Disney/User-Study/analysis_full"
OUT = "plots"
os.makedirs(OUT, exist_ok=True)

for f in ["calibri.ttf", "calibrib.ttf", "calibrii.ttf"]:
    font_manager.fontManager.addfont(f"/mnt/c/Windows/Fonts/{f}")
plt.rcParams.update(
    {
        "font.family": "Calibri",
        "font.size": 15,
        "text.color": "#1E2A4A",
        "axes.labelcolor": "#5B6B8C",
        "xtick.color": "#1E2A4A",
        "ytick.color": "#5B6B8C",
        "axes.edgecolor": "#C9D3E3",
        "savefig.dpi": 300,
        "savefig.transparent": True,
    }
)
INK, MUTED, GRID = "#1E2A4A", "#5B6B8C", "#E3EAF5"
COL = {"baseline": "#9AA5B8", "director": "#2F6FDE", "time_constrained": "#7B5CD6"}
XLAB = {
    "baseline": "Baseline\n(Frozen)",
    "director": "Director\n(both stories)",
    "time_constrained": "Time-constrained\n(Cinderella)",
}
ORDER = ["baseline", "director", "time_constrained"]

phases = pd.read_csv(f"{DATA}/phases.csv")
participants = pd.read_csv(f"{DATA}/participants.csv")
participants = participants[participants["n_phases_reached"] > 0]
completers = set(participants.loc[participants["dropout_stage"] == "completed", "participant_id"])
comp = phases[phases["participant_id"].isin(completers)]
print("completers:", len(completers))

MEASURES = [
    ("q1_coherence", "coherence"),
    ("q2_in_character", "character"),
    ("q4_engagement", "engaging"),
    ("q5_overall", "overall"),
    ("q6_resist_stayed_on_track", "resist"),
]


def style(ax):
    """Apply the shared axis style."""
    for sp in ["top", "right"]:
        ax.spines[sp].set_visible(False)
    ax.spines["left"].set_color("#C9D3E3")
    ax.spines["bottom"].set_color("#C9D3E3")
    ax.yaxis.grid(True, color=GRID, lw=1)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)


def likert_bars(stats, fname, size=(8.0, 4.9)):
    """Bar chart of Likert means with error bars per condition."""
    fig, ax = plt.subplots(figsize=size)
    style(ax)
    for i, c in enumerate(ORDER):
        m, sd, n = stats[c]
        ax.bar(i, m, width=0.6, color=COL[c], zorder=2)
        ax.errorbar(
            i, m, yerr=sd, fmt="none", ecolor=INK, elinewidth=1.6, capsize=8, capthick=1.6, zorder=3
        )
        ax.text(
            i,
            m + sd + 0.12,
            f"{m:.2f} ± {sd:.2f}",
            ha="center",
            va="bottom",
            fontsize=16,
            fontweight="bold",
            color=INK,
            zorder=5,
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none"),
        )
        ax.text(
            i,
            0.12,
            f"n = {n}",
            ha="center",
            va="bottom",
            fontsize=12,
            color="white",
            fontweight="bold",
            zorder=4,
        )
    ax.axhline(3, color=MUTED, ls=(0, (4, 4)), lw=1.2, zorder=1)
    ax.text(-0.52, 3.05, "neutral", fontsize=12, color=MUTED, ha="left", va="bottom", zorder=5)
    ax.set_xticks(range(3))
    ax.set_xticklabels([XLAB[c] for c in ORDER], fontsize=15)
    ax.set_ylim(0, 6.0)
    ax.set_yticks(range(0, 6))
    ax.set_ylabel("Rating (1–5), mean ± SD", fontsize=14)
    ax.set_xlim(-0.55, 2.55)
    fig.tight_layout()
    fig.savefig(f"{OUT}/{fname}")
    plt.close(fig)


def msd(v):
    """Mean, sample SD and n of a sequence."""
    v = np.asarray(v, dtype=float)
    return float(v.mean()), float(v.std(ddof=1)), int(len(v))


# ---------- per-measure plots (pooled, exactly like plot 05) ----------
allv = {c: [] for c in ORDER}
summary = {}
for col, key in MEASURES:
    st = {}
    for c in ORDER:
        v = comp.loc[comp["condition"] == c, col].dropna()
        st[c] = msd(v)
        allv[c].extend(v.values)
    summary[key] = st
    likert_bars(st, f"q_{key}.png")
# plot 05 uses population SD (np.std) for the combined panel
st = {}
for c in ORDER:
    v = np.array(allv[c], dtype=float)
    st[c] = (float(v.mean()), float(v.std()), int(len(v)))
summary["all"] = st
likert_bars(st, "q_all.png")
for k, s in summary.items():
    print(k, {c: tuple(round(x, 2) for x in s[c]) for c in ORDER})


# ---------- paired Wilcoxon per story ----------
def paired(story, a, b, col):
    """Paired values of one column for two conditions in one story."""
    s = comp[comp["story"] == story]
    pa = s[s["condition"] == a].set_index("participant_id")[col]
    pb = s[s["condition"] == b].set_index("participant_id")[col]
    d = pd.concat([pa, pb], axis=1, keys=[a, b]).dropna()
    return wilcoxon(d[a], d[b]).pvalue, len(d)


for col, key in MEASURES:
    p1, n1 = paired(1, "director", "baseline", col)
    p2, n2 = paired(2, "director", "time_constrained", col)
    print(f"{key:10s} Frozen p={p1:.3f} (n={n1})   Cinderella p={p2:.3f} (n={n2})")
p_end, n_end = paired(2, "director", "time_constrained", "q8_ending_satisfying")
s2 = comp[comp["story"] == 2]
print(
    "ending",
    {
        c: msd(s2.loc[s2.condition == c, "q8_ending_satisfying"].dropna())[:2]
        for c in ["director", "time_constrained"]
    },
    f"p={p_end:.3f}",
)

# ---------- pacing verdict (story 2) ----------
cats = [
    ("well-paced", "Well-paced", "#2E8B6A"),
    ("rushed", "Rushed", "#E8B64C"),
    ("cut-short", "Cut short", "#D1495B"),
]
conds = ["director", "time_constrained"]
counts = {c: s2.loc[s2["condition"] == c, "q_pacing"].value_counts() for c in conds}
print("pacing", {c: counts[c].to_dict() for c in conds})
fig, ax = plt.subplots(figsize=(7.6, 4.9))
style(ax)
for i, c in enumerate(conds):
    bottom = 0
    for key, lab, color in cats:
        v = int(counts[c].get(key, 0))
        if v:
            ax.bar(
                i,
                v,
                bottom=bottom,
                width=0.55,
                color=color,
                edgecolor="white",
                linewidth=2,
                zorder=2,
            )
            ax.text(
                i,
                bottom + v / 2,
                str(v),
                ha="center",
                va="center",
                color="white",
                fontsize=18,
                fontweight="bold",
            )
        bottom += v
ax.set_xticks([0, 1])
ax.set_xticklabels(["Director\n(no clock)", "Time-constrained\n(5-min budget)"], fontsize=15)
ax.set_ylim(0, 14.5)
ax.set_yticks(range(0, 15, 2))
ax.set_ylabel("Participants (n = 14 per condition)", fontsize=14)
ax.set_xlim(-0.6, 2.25)
handles = [plt.Rectangle((0, 0), 1, 1, color=color) for _, _, color in cats]
ax.legend(handles, [lab for _, lab, _ in cats], loc="center right", frameon=False, fontsize=15)
fig.tight_layout()
fig.savefig(f"{OUT}/pacing.png")
plt.close(fig)

# ---------- appendix: Frozen, humans vs judge ----------
s1 = comp[comp["story"] == 1]
labels_h = ["Coherence", "Character", "Engaging", "Overall", "On track"]
fig, ax = plt.subplots(figsize=(6.2, 4.4))
style(ax)
x = np.arange(len(MEASURES))
w = 0.38
for j, c in enumerate(["baseline", "director"]):
    ms, sds = [], []
    for col, _ in MEASURES:
        m, sd, _ = msd(s1.loc[s1["condition"] == c, col].dropna())
        ms.append(m)
        sds.append(sd)
    xs = x + (j - 0.5) * w
    ax.bar(xs, ms, w, color=COL[c], zorder=2, label=c.capitalize())
    ax.errorbar(xs, ms, yerr=sds, fmt="none", ecolor=INK, elinewidth=1.2, capsize=4, zorder=3)
    for xi, m in zip(xs, ms):
        ax.text(
            xi,
            0.1,
            f"{m:.1f}",
            ha="center",
            va="bottom",
            fontsize=11,
            color="white",
            fontweight="bold",
            zorder=4,
        )
ax.set_xticks(x)
ax.set_xticklabels(labels_h, fontsize=13)
ax.set_ylim(0, 6)
ax.set_yticks(range(0, 6))
ax.set_ylabel("Rating (1–5), mean ± SD", fontsize=13)
ax.legend(frameon=False, fontsize=13, loc="upper left", ncol=2)
fig.tight_layout()
fig.savefig(f"{OUT}/frozen_humans.png")
plt.close(fig)

# values from Implementation/generate_case_study_plots.py (thesis Figure 4.19)
FROZEN_BASELINE = {
    "Plot": 3.44,
    "Development": 4.15,
    "Language Use": 8.82,
    "Interruption Handling": 3.88,
    "Character Fidelity": 8.42,
    "Narrative Control": 3.12,
    "Anthropomorphism": 6.55,
    "Overall": 5.48,
}
FROZEN_DIRECTOR = {
    "Plot": 8.74,
    "Development": 8.54,
    "Language Use": 8.62,
    "Interruption Handling": 8.89,
    "Character Fidelity": 8.51,
    "Narrative Control": 8.54,
    "Anthropomorphism": 8.86,
    "Overall": 8.67,
}
dims = list(FROZEN_BASELINE)
short = [
    "Plot",
    "Develop.",
    "Language",
    "Interrupt.",
    "Character",
    "Narr. ctrl",
    "Anthrop.",
    "Overall",
]
fig, ax = plt.subplots(figsize=(6.2, 4.4))
style(ax)
x = np.arange(len(dims))
for j, (c, d) in enumerate([("baseline", FROZEN_BASELINE), ("director", FROZEN_DIRECTOR)]):
    xs = x + (j - 0.5) * w
    ax.bar(xs, [d[k] for k in dims], w, color=COL[c], zorder=2, label=c.capitalize())
    for xi, k in zip(xs, dims):
        ax.text(xi, d[k] + 0.12, f"{d[k]:.1f}", ha="center", va="bottom", fontsize=10, color=INK)
ax.set_xticks(x)
ax.set_xticklabels(short, fontsize=12, rotation=35, ha="right", rotation_mode="anchor")
ax.set_ylim(0, 11.5)
ax.set_yticks(range(0, 11, 2))
ax.set_ylabel("Judge score (0–10), mean of 5 runs", fontsize=13)
ax.legend(frameon=False, fontsize=13, loc="upper left", ncol=2)
fig.tight_layout()
fig.savefig(f"{OUT}/frozen_judge.png")
plt.close(fig)
print("plots written")
