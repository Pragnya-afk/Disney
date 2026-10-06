"""
Statistical analysis of the corrected/current User-Study dataset.
Run build_dataset.py first. Outputs stats_report.txt.
"""

import os
import io

import numpy as np
import pandas as pd
from scipy import stats

HERE = os.path.dirname(__file__)

phases = pd.read_csv(os.path.join(HERE, "phases.csv"))
participants = pd.read_csv(os.path.join(HERE, "participants.csv"))
participants = participants[participants["n_phases_reached"] > 0].copy()

report = io.StringIO()


def sec(title):
    report.write("\n" + "=" * 70 + "\n" + title + "\n" + "=" * 70 + "\n")


sec("1. RETENTION FUNNEL (N=28 unique participants; restarts deduped, latest attempt kept)")
n = len(participants)
reached = {k: (participants["n_phases_reached"] >= k).sum() for k in [1, 2, 3, 4]}
completed = (participants["dropout_stage"] == "completed").sum()
report.write(f"N participants (started) = {n}\n")
for k in [1, 2, 3, 4]:
    report.write(f"  reached phase {k}: {reached[k]}/{n} ({100*reached[k]/n:.0f}%)\n")
report.write(
    f"  completed (finished phase 4 story + submitted final questionnaire): {completed}/{n} ({100*completed/n:.0f}%)\n"
)
report.write("\nDropout stage breakdown:\n")
report.write(participants["dropout_stage"].value_counts().to_string())
report.write("\n")

sec("2. DOES FIRST-CONDITION-SHOWN PREDICT PHASE-1 DROPOUT?")
p1 = participants.copy()
p1["dropped_at_1"] = p1["dropout_stage"] == "phase_1_mid_story"
ct = pd.crosstab(p1["first_condition"], p1["dropped_at_1"])
report.write("Contingency table (first_condition x dropped_at_phase_1):\n")
report.write(ct.to_string() + "\n\n")
if ct.shape == (2, 2):
    odds, p = stats.fisher_exact(ct.values)
    report.write(f"Fisher's exact test: odds ratio={odds:.2f}, p={p:.3f}\n")
report.write("Interpretation: N this small (~28) -> descriptive, not confirmatory.\n")
report.write(
    "Cross-check against qualitative turn counts: participants who abandoned in phase 1 while\n"
    "shown baseline first averaged more turns before quitting than those shown director first\n"
    "(see analysis_2 discussion) -- consistent with 'abandonment is not primarily a condition\n"
    "effect' rather than baseline-frustration-driven dropout.\n"
)

sec("3. QUESTIONNAIRE OUTCOMES BY CONDITION -- ALL AVAILABLE RESPONSES (unpaired, N=28)")
outcome_cols = [
    "q1_coherence",
    "q2_in_character",
    "q4_engagement",
    "q5_overall",
    "q6_resist_stayed_on_track",
]
for col in outcome_cols:
    sub = phases[["condition", col]].dropna()
    if sub.empty:
        continue
    groups = {c: g[col].values for c, g in sub.groupby("condition")}
    report.write(f"\n{col}:\n")
    for c, v in groups.items():
        report.write(f"  {c:18s} mean={np.mean(v):.2f}  sd={np.std(v, ddof=1):.2f}  n={len(v)}\n")
    vals = [g for g in groups.values() if len(g) > 1]
    names = [c for c, g in groups.items() if len(g) > 1]
    if len(vals) >= 3:
        h, p = stats.kruskal(*vals)
        report.write(f"  Kruskal-Wallis across {names}: H={h:.2f}, p={p:.4f}\n")
report.write(
    "\nNote: unpaired -- double-counts participants who answered more than one questionnaire.\n"
    "Sections 4-5 give the within-subject (paired, completers-only) version, which is the\n"
    "statistically correct comparison for this design.\n"
)

sec("4. PAIRED WITHIN-SUBJECT: STORY 1 director vs baseline (n=14 completers)")
completers = set(participants.loc[participants["dropout_stage"] == "completed", "participant_id"])
comp_phases = phases[phases["participant_id"].isin(completers)]
s1 = comp_phases[comp_phases["story"] == 1]
wide1 = s1.pivot_table(
    index="participant_id",
    columns="condition",
    values=[
        "q1_coherence",
        "q2_in_character",
        "q4_engagement",
        "q5_overall",
        "q6_resist_stayed_on_track",
    ],
)
for metric in [
    "q1_coherence",
    "q2_in_character",
    "q4_engagement",
    "q5_overall",
    "q6_resist_stayed_on_track",
]:
    pair = wide1[metric][["director", "baseline"]].dropna()
    if len(pair) >= 2:
        stat_, p = stats.wilcoxon(pair["director"], pair["baseline"])
        report.write(
            f"{metric:28s} n={len(pair):2d}  director={pair['director'].mean():.2f}  "
            f"baseline={pair['baseline'].mean():.2f}  Wilcoxon p={p:.4f}\n"
        )

sec("5. PAIRED WITHIN-SUBJECT: STORY 2 director vs time_constrained (n=14 completers)")
s2 = comp_phases[comp_phases["story"] == 2]
wide2 = s2.pivot_table(
    index="participant_id",
    columns="condition",
    values=[
        "q1_coherence",
        "q2_in_character",
        "q4_engagement",
        "q5_overall",
        "q6_resist_stayed_on_track",
    ],
)
for metric in [
    "q1_coherence",
    "q2_in_character",
    "q4_engagement",
    "q5_overall",
    "q6_resist_stayed_on_track",
]:
    pair = wide2[metric][["director", "time_constrained"]].dropna()
    if len(pair) >= 2:
        stat_, p = stats.wilcoxon(pair["director"], pair["time_constrained"])
        report.write(
            f"{metric:28s} n={len(pair):2d}  director={pair['director'].mean():.2f}  "
            f"time_constrained={pair['time_constrained'].mean():.2f}  Wilcoxon p={p:.4f}\n"
        )

sec(
    "6. ORDER EFFECT: does 1st-seen vs 2nd-seen condition change overall rating? (all 28 participants)"
)
ord_df = phases.dropna(subset=["order_position", "q5_overall"])
g1 = ord_df[ord_df["order_position"] == 1]["q5_overall"]
g2 = ord_df[ord_df["order_position"] == 2]["q5_overall"]
report.write(f"1st-seen: n={len(g1)} mean={g1.mean():.2f} sd={g1.std():.2f}\n")
report.write(f"2nd-seen: n={len(g2)} mean={g2.mean():.2f} sd={g2.std():.2f}\n")
if len(g1) > 1 and len(g2) > 1:
    u, p = stats.mannwhitneyu(g1, g2, alternative="two-sided")
    report.write(f"Mann-Whitney U: U={u:.1f}, p={p:.3f}\n")

sec("7. ENGAGEMENT PROXY: completion_ratio and n_turns by condition (all 28 participants)")
for col in ["completion_ratio", "n_turns"]:
    g = phases.groupby("condition")[col].agg(["mean", "std", "count"])
    report.write(f"\n{col}:\n{g.to_string()}\n")

with open(os.path.join(HERE, "stats_report.txt"), "w") as f:
    f.write(report.getvalue())

print(report.getvalue())
print(f"\nFull report written to {os.path.join(HERE, 'stats_report.txt')}")
