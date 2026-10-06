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
COND_ORDER = ["baseline", "director", "time_constrained"]
COND_LABELS = {
    "baseline": "Baseline",
    "director": "Director",
    "time_constrained": "Time-constrained",
}


# --- Plot 1: retention funnel (corrected N=28, "completed" = finished phase 4 + questionnaire) ---
n = len(participants)
counts = [(participants["n_phases_reached"] >= k).sum() for k in [1, 2, 3, 4]]
completed = (participants["dropout_stage"] == "completed").sum()

fig, ax = plt.subplots(figsize=(7, 4.5))
xs = ["Phase 1", "Phase 2", "Phase 3", "Phase 4", "Completed\n(phase 4 +\nfinal survey)"]
ys = counts + [completed]
bars = ax.bar(xs, ys, color=["#4C72B0"] * 4 + ["#2ca02c"])
for b, y in zip(bars, ys):
    ax.text(
        b.get_x() + b.get_width() / 2,
        y + 0.3,
        f"{y}/{n}\n({100*y/n:.0f}%)",
        ha="center",
        va="bottom",
        fontsize=9,
    )
ax.set_ylabel("Participants reaching this point")
ax.set_title(f"Retention funnel (N={n} unique participants, restarts deduped)")
ax.set_ylim(0, n + 4)
fig.tight_layout()
fig.savefig(os.path.join(PLOTS_DIR, "01_retention_funnel.png"), dpi=150)
plt.close(fig)

# --- Plot 2: phase-1 dropout by first condition shown ---
p1 = participants.copy()
p1["dropped_at_1"] = p1["dropout_stage"] == "phase_1_mid_story"
grp = p1.groupby("first_condition")["dropped_at_1"].agg(["sum", "count"])
labels = grp.index.tolist()
counts = [grp.loc[c, "sum"] for c in labels]

fig, ax = plt.subplots(figsize=(5.5, 4.5))
colors = [COND_COLORS.get(c, "#888") for c in labels]
bars = ax.bar(labels, counts, color=colors)
for b, c, cnt in zip(bars, labels, counts):
    ax.text(
        b.get_x() + b.get_width() / 2,
        cnt + 0.1,
        f"{cnt} of {grp.loc[c,'count']} shown {c} first",
        ha="center",
        fontsize=9,
    )
ax.set_ylabel("Number of participants who dropped out during phase 1")
ax.set_title("Phase-1 dropouts by first condition shown (N=28)")
ax.set_ylim(0, max(counts) + 2)
fig.tight_layout()
fig.savefig(os.path.join(PLOTS_DIR, "02_phase1_dropout_by_first_condition.png"), dpi=150)
plt.close(fig)

# --- Plot 3: questionnaire outcomes by condition, ALL available responses (unpaired, N=28) ---
outcome_cols = [
    ("q1_coherence", "Story felt coherent (1-5)"),
    ("q2_in_character", "Olaf stayed in character (1-5)"),
    ("q4_engagement", "Engaging / enjoyable (1-5)"),
    ("q5_overall", "Overall rating (1-5)"),
    ("q6_resist_stayed_on_track", "Stayed on track despite derailment (1-5)"),
]
fig, axes = plt.subplots(1, len(outcome_cols), figsize=(4 * len(outcome_cols), 4.5), sharey=True)
for ax, (col, label) in zip(axes, outcome_cols):
    means, sds, ns = [], [], []
    for c in COND_ORDER:
        v = phases.loc[phases["condition"] == c, col].dropna()
        means.append(v.mean() if len(v) else np.nan)
        sds.append(v.std() if len(v) > 1 else 0)
        ns.append(len(v))
    colors = [COND_COLORS[c] for c in COND_ORDER]
    ax.bar(COND_ORDER, means, yerr=sds, capsize=5, color=colors)
    for i, c in enumerate(COND_ORDER):
        if ns[i]:
            ax.text(i, 0.15, f"n={ns[i]}", ha="center", fontsize=8, color="white")
    ax.set_title(label, fontsize=10)
    ax.set_ylim(0, 5.6)
    ax.tick_params(axis="x", rotation=20)
axes[0].set_ylabel("Rating (mean +/- SD)")
fig.suptitle(
    "Questionnaire outcomes by condition -- all available responses, unpaired (N=28 participants)"
)
fig.tight_layout(rect=[0, 0, 1, 0.94])
fig.savefig(os.path.join(PLOTS_DIR, "03_questionnaire_all_responses_by_condition.png"), dpi=150)
plt.close(fig)

# --- Plot 4: engagement proxy (n_turns) by condition ---
fig, ax = plt.subplots(figsize=(6, 5))
data = [phases.loc[phases["condition"] == c, "n_turns"].dropna().values for c in COND_ORDER]
bp = ax.boxplot(data, tick_labels=COND_ORDER, patch_artist=True)
for patch, c in zip(bp["boxes"], COND_ORDER):
    patch.set_facecolor(COND_COLORS[c])
    patch.set_alpha(0.6)
ax.set_ylabel("Turns per phase")
ax.set_title(
    "Conversation length by condition\n(beats_completed excluded -- unreliable for\ndirector/baseline; see report)"
)
fig.tight_layout()
fig.savefig(os.path.join(PLOTS_DIR, "04_turns_by_condition.png"), dpi=150)
plt.close(fig)

# --- Plot 5: completers-only (n=14), all measures with SD ---
completers = set(participants.loc[participants["dropout_stage"] == "completed", "participant_id"])
comp = phases[phases["participant_id"].isin(completers)]

measures = [
    ("q1_coherence", "Story Coherence"),
    ("q2_in_character", "Maintained Character"),
    ("q4_engagement", "Engaging / Enjoyable"),
    ("q5_overall", "Overall Rating"),
    ("q6_resist_stayed_on_track", "Resistance to Derailment"),
]
fig, axes = plt.subplots(2, 3, figsize=(15, 9.5))
axes = axes.flatten()
all_vals = {c: [] for c in COND_ORDER}
for ax, (col, title) in zip(axes, measures):
    tops = []
    for i, c in enumerate(COND_ORDER):
        v = comp.loc[comp["condition"] == c, col].dropna()
        m, s = (v.mean(), v.std()) if len(v) > 1 else (v.mean() if len(v) else np.nan, 0)
        ax.bar(i, m, yerr=s, capsize=5, color=COND_COLORS[c])
        if not np.isnan(m):
            ax.text(
                i, m + s + 0.15, f"{m:.2f} +/- {s:.2f}", ha="center", fontsize=9, fontweight="bold"
            )
            tops.append(m + s)
        all_vals[c].extend(v.values)
    ax.set_xticks([])
    ax.set_xlim(-0.7, 2.7)
    ax.set_ylim(0, max(5.6, max(tops, default=0) + 0.6))
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.axhline(3, color="gray", ls="--", lw=0.7)
ax = axes[5]
tops = []
for i, c in enumerate(COND_ORDER):
    v = np.array(all_vals[c])
    m, s = v.mean(), v.std()
    ax.bar(i, m, yerr=s, capsize=5, color=COND_COLORS[c])
    ax.text(i, m + s + 0.15, f"{m:.2f} +/- {s:.2f}", ha="center", fontsize=9, fontweight="bold")
    tops.append(m + s)
ax.set_xticks([])
ax.set_xlim(-0.7, 2.7)
ax.set_ylim(0, max(5.6, max(tops, default=0) + 0.6))
ax.set_title("All Measures Combined", fontsize=11, fontweight="bold")
ax.axhline(3, color="gray", ls="--", lw=0.7)
fig.suptitle(
    f"Questionnaire Responses by Condition (Complete Participants Only, n={len(completers)})",
    fontsize=14,
    fontweight="bold",
)
legend_handles = [Patch(facecolor=COND_COLORS[c], label=COND_LABELS[c]) for c in COND_ORDER]
fig.legend(
    handles=legend_handles,
    loc="lower center",
    ncol=3,
    fontsize=11,
    frameon=False,
    bbox_to_anchor=(0.5, 0.0),
)
fig.tight_layout(rect=[0, 0.05, 1, 0.95])
fig.savefig(os.path.join(PLOTS_DIR, "05_completers_all_measures.png"), dpi=150)
plt.close(fig)

# --- Plot 6: story 1 vs story 2 coherence, completers only ---
fig, axes = plt.subplots(1, 2, figsize=(11, 5))
s1 = comp[comp["story"] == 1]
ax = axes[0]
for i, c in enumerate(["director", "baseline"]):
    v = s1.loc[s1["condition"] == c, "q1_coherence"].dropna()
    m, s = v.mean(), v.std()
    ax.bar(i, m, yerr=s, capsize=5, color=COND_COLORS[c])
    ax.text(i, m + s + 0.08, f"{m:.2f}\n+/-{s:.2f}", ha="center", fontsize=10, fontweight="bold")
ax.set_xticks([0, 1])
ax.set_xticklabels(["director", "baseline"])
ax.set_ylim(0, 5.6)
ax.set_title("Story 1: Frozen", fontweight="bold")
ax.set_ylabel("Coherence Rating")

s2 = comp[comp["story"] == 2]
ax = axes[1]
for i, c in enumerate(["director", "time_constrained"]):
    v = s2.loc[s2["condition"] == c, "q1_coherence"].dropna()
    m, s = v.mean(), v.std()
    ax.bar(i, m, yerr=s, capsize=5, color=COND_COLORS[c])
    ax.text(i, m + s + 0.08, f"{m:.2f}\n+/-{s:.2f}", ha="center", fontsize=10, fontweight="bold")
ax.set_xticks([0, 1])
ax.set_xticklabels(["director", "time_constrained"])
ax.set_ylim(0, 5.6)
ax.set_title("Story 2: Cinderella", fontweight="bold")

fig.suptitle(
    f"Coherence by Story and Condition (Complete Participants, n={len(completers)})",
    fontsize=13,
    fontweight="bold",
)
fig.tight_layout(rect=[0, 0, 1, 0.93])
fig.savefig(os.path.join(PLOTS_DIR, "06_story_comparison.png"), dpi=150)
plt.close(fig)

# Plots 7-8 use only phases where the participant actually finished that
# phase and submitted its questionnaire -- excludes phases abandoned mid-story.
completed_phases = phases[phases["has_questionnaire"] == True]  # noqa: E712

# --- Plot 7: beats completed by condition, mean +/- SD (questionnaire-completed phases only) ---
fig, ax = plt.subplots(figsize=(7.5, 5.5))
means, sds = {}, {}
for c in COND_ORDER:
    v = completed_phases.loc[completed_phases["condition"] == c, "beats_completed"].dropna()
    means[c], sds[c] = v.mean(), v.std()
top = max(means[c] + sds[c] for c in COND_ORDER)
for i, c in enumerate(COND_ORDER):
    v = completed_phases.loc[completed_phases["condition"] == c, "beats_completed"].dropna()
    m, s = means[c], sds[c]
    ax.bar(i, m, yerr=s, capsize=5, color=COND_COLORS[c])
    ax.text(
        i,
        m + s + top * 0.05,
        f"{m:.2f}\n+/-{s:.2f}\nn={len(v)}",
        ha="center",
        fontsize=9,
        fontweight="bold",
    )
ax.set_xticks(range(3))
ax.set_xticklabels(COND_ORDER)
ax.set_ylim(0, top * 1.35)
ax.set_ylabel("Beats completed")
ax.set_title(
    "Beats completed by condition (questionnaire-completed phases only, mean +/- SD)", fontsize=10.5
)
fig.tight_layout()
fig.savefig(os.path.join(PLOTS_DIR, "07_beats_completed_by_condition.png"), dpi=150)
plt.close(fig)

# --- Plot 8: turns per phase by condition, mean +/- SD (questionnaire-completed phases only) ---
fig, ax = plt.subplots(figsize=(7.5, 5))
means, sds = {}, {}
for c in COND_ORDER:
    v = completed_phases.loc[completed_phases["condition"] == c, "n_turns"].dropna()
    means[c], sds[c] = v.mean(), v.std()
top = max(means[c] + sds[c] for c in COND_ORDER)
for i, c in enumerate(COND_ORDER):
    v = completed_phases.loc[completed_phases["condition"] == c, "n_turns"].dropna()
    m, s = means[c], sds[c]
    ax.bar(i, m, yerr=s, capsize=5, color=COND_COLORS[c])
    ax.text(
        i,
        m + s + top * 0.05,
        f"{m:.2f}\n+/-{s:.2f}\nn={len(v)}",
        ha="center",
        fontsize=9,
        fontweight="bold",
    )
ax.set_xticks(range(3))
ax.set_xticklabels(COND_ORDER)
ax.set_ylim(0, top * 1.3)
ax.set_ylabel("Turns per phase")
ax.set_title(
    "Turns per phase by condition (questionnaire-completed phases only, mean +/- SD)", fontsize=11
)
fig.tight_layout()
fig.savefig(os.path.join(PLOTS_DIR, "08_turns_mean_sd_by_condition.png"), dpi=150)
plt.close(fig)

print("Wrote plots to", PLOTS_DIR)
for f in sorted(os.listdir(PLOTS_DIR)):
    print(" -", f)
