"""
generate_generalization_beats_plots.py

Generates plots matching the style of evaluation_summary/plots/01-07
(same colors, layout, title format) for the two new comparisons written
up in generalization_and_beats_ablation_section.tex:

  08_rocket_scores_by_metric.png       baseline vs director, Rocket (n=7)
  09_rocket_pairwise_wins.png          pairwise verdicts, Rocket (n=7)
  10_rocket_by_derailment_level.png    Rocket Overall vs derailment severity
  11_beats_vs_fulltext_scores_by_metric.png
  12_beats_vs_fulltext_pairwise_wins.png
  13_beats_vs_fulltext_by_scenario.png

Usage (from Implementation/):
    python generate_generalization_beats_plots.py
"""

import json
import glob
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT_DIR = Path(__file__).parent / "evaluation_summary" / "plots"
OUT_DIR.mkdir(parents=True, exist_ok=True)

METRICS = [
    "Plot", "Development", "Language Use", "Interruption Handling",
    "Character Fidelity", "Narrative Control", "Anthropomorphism", "Overall",
]
METRIC_LABELS = [m.replace(" ", "\n") for m in METRICS]

BLUE = "#4c72b0"
ORANGE = "#dd8452"
GRAY = "#d3d3d3"

plt.rcParams["font.size"] = 12


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# Data loading: rocket baseline vs director

def load_rocket_bvd():
    paths = sorted(glob.glob("evaluation_results/baseline_vs_director/rocket_*/eval_run_1.json"))
    sum_a, sum_b, n_a, n_b = defaultdict(float), defaultdict(float), defaultdict(int), defaultdict(int)
    wins_a, wins_b, ties = defaultdict(int), defaultdict(int), defaultdict(int)
    per_scenario = {}
    for p in paths:
        d = load(p)
        a = d["single_story_scores"]["A"]["scores"]
        b = d["single_story_scores"]["B"]["scores"]
        for m in METRICS:
            if a.get(m) is not None:
                sum_a[m] += a[m]; n_a[m] += 1
            if b.get(m) is not None:
                sum_b[m] += b[m]; n_b[m] += 1
        for m, w in d.get("aggregated_ab_ba_winners", {}).items():
            if m not in METRICS:
                continue
            if w == "A": wins_a[m] += 1
            elif w == "B": wins_b[m] += 1
            else: ties[m] += 1
        per_scenario[d["scenario"]] = (a.get("Overall"), b.get("Overall"))
    avg_a = {m: sum_a[m] / n_a[m] for m in METRICS if n_a[m]}
    avg_b = {m: sum_b[m] / n_b[m] for m in METRICS if n_b[m]}
    return avg_a, avg_b, wins_a, wins_b, ties, per_scenario


def load_rocket_derailment():
    groups = {
        "None": ["rocket_retells_red_riding_hood_no_derailment"],
        "Medium": [
            "rocket_retells_red_riding_hood_medium_derailment",
            "rocket_retells_red_riding_hood_medium_adversarial",
            "rocket_retells_red_riding_hood_medium_targeted",
        ],
        "Complete": [
            "rocket_retells_red_riding_hood_complete_derailment",
            "rocket_retells_red_riding_hood_complete_adversarial",
            "rocket_retells_red_riding_hood_complete_targeted",
        ],
    }
    baseline, director = {}, {}
    for level, scenarios in groups.items():
        a_vals, b_vals = [], []
        for s in scenarios:
            d = load(f"evaluation_results/baseline_vs_director/{s}/eval_run_1.json")
            a = d["single_story_scores"]["A"]["scores"].get("Overall")
            b = d["single_story_scores"]["B"]["scores"].get("Overall")
            if a is not None: a_vals.append(a)
            if b is not None: b_vals.append(b)
        baseline[level] = sum(a_vals) / len(a_vals)
        director[level] = sum(b_vals) / len(b_vals)
    return baseline, director


def load_beats_vs_fulltext():
    paths = sorted(glob.glob("evaluation_results/beats_vs_fulltext_director/*/eval_run_1.json"))
    sum_a, sum_b, n_a, n_b = defaultdict(float), defaultdict(float), defaultdict(int), defaultdict(int)
    wins_a, wins_b, ties = defaultdict(int), defaultdict(int), defaultdict(int)
    per_scenario = {}
    for p in paths:
        d = load(p)
        a = d["single_story_scores"]["A_beats_director"]["scores"]
        b = d["single_story_scores"]["B_fulltext_director"]["scores"]
        for m in METRICS:
            if a.get(m) is not None:
                sum_a[m] += a[m]; n_a[m] += 1
            if b.get(m) is not None:
                sum_b[m] += b[m]; n_b[m] += 1
        for m, w in d.get("aggregated_ab_ba_winners", {}).items():
            if m not in METRICS:
                continue
            if w == "A": wins_a[m] += 1
            elif w == "B": wins_b[m] += 1
            else: ties[m] += 1
        per_scenario[d["scenario"]] = (a.get("Overall"), b.get("Overall"))
    avg_a = {m: sum_a[m] / n_a[m] for m in METRICS if n_a[m]}
    avg_b = {m: sum_b[m] / n_b[m] for m in METRICS if n_b[m]}
    return avg_a, avg_b, wins_a, wins_b, ties, per_scenario


# Plot helpers

def grouped_bar_scores(avg_a, avg_b, label_a, label_b, title, subtitle, out_name):
    x = range(len(METRICS))
    width = 0.38
    fig, ax = plt.subplots(figsize=(13, 6.5))
    bars_a = ax.bar([i - width / 2 for i in x], [avg_a[m] for m in METRICS], width, label=label_a, color=ORANGE)
    bars_b = ax.bar([i + width / 2 for i in x], [avg_b[m] for m in METRICS], width, label=label_b, color=BLUE)
    for bars in (bars_a, bars_b):
        for rect in bars:
            h = rect.get_height()
            ax.annotate(f"{h:.1f}", (rect.get_x() + rect.get_width() / 2, h),
                        xytext=(0, 3), textcoords="offset points", ha="center", fontsize=11)
    ax.set_ylim(0, 11)
    ax.set_yticks(range(0, 11, 2))
    ax.set_ylabel("Mean judge score (0-10)")
    ax.set_xticks(list(x))
    ax.set_xticklabels(METRIC_LABELS)
    ax.set_title(f"{title}\n{subtitle}")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT_DIR / out_name, dpi=150)
    plt.close(fig)


def stacked_pairwise_wins(wins_a, wins_b, ties, n, label_a, label_b, title, subtitle, out_name):
    fig, ax = plt.subplots(figsize=(13, 7.5))
    x = range(len(METRICS))
    a_vals = [wins_a[m] for m in METRICS]
    tie_vals = [ties[m] for m in METRICS]
    b_vals = [wins_b[m] for m in METRICS]

    ax.bar(x, a_vals, color=ORANGE, label=f"{label_a} wins")
    ax.bar(x, tie_vals, bottom=a_vals, color=GRAY, label="Tie")
    bottoms2 = [a + t for a, t in zip(a_vals, tie_vals)]
    ax.bar(x, b_vals, bottom=bottoms2, color=BLUE, label=f"{label_b} wins")

    for i in x:
        cum = 0
        for val, color in ((a_vals[i], "white"), (tie_vals[i], "black"), (b_vals[i], "white")):
            if val > 0:
                ax.text(i, cum + val / 2, str(val), ha="center", va="center", color=color, fontsize=11)
            cum += val

    ax.set_xticks(list(x))
    ax.set_xticklabels(METRIC_LABELS)
    ax.set_ylabel(f"Number of scenario comparisons (of {n})")
    ax.set_title(f"{title}\n{subtitle}")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=3)
    fig.tight_layout()
    fig.savefig(OUT_DIR / out_name, dpi=150)
    plt.close(fig)


def derailment_level_bar(baseline, director, title, out_name):
    levels = ["None", "Medium", "Complete"]
    x = range(len(levels))
    width = 0.35
    fig, ax = plt.subplots(figsize=(7, 6.5))
    bars_a = ax.bar([i - width / 2 for i in x], [baseline[l] for l in levels], width, label="Baseline", color=ORANGE)
    bars_b = ax.bar([i + width / 2 for i in x], [director[l] for l in levels], width, label="Director", color=BLUE)
    for bars in (bars_a, bars_b):
        for rect in bars:
            h = rect.get_height()
            ax.annotate(f"{h:.2f}", (rect.get_x() + rect.get_width() / 2, h),
                        xytext=(0, 3), textcoords="offset points", ha="center", fontsize=11)
    ax.set_ylim(0, 11)
    ax.set_yticks(range(0, 11, 2))
    ax.set_ylabel("Mean Overall score (0-10)")
    ax.set_xlabel("Derailment level in scenario")
    ax.set_xticks(list(x))
    ax.set_xticklabels(levels)
    ax.set_title(title)
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT_DIR / out_name, dpi=150)
    plt.close(fig)


def per_scenario_bar(per_scenario, label_a, label_b, title, subtitle, out_name):
    order = [
        "olaf_retells_red_riding_hood_no_derailment",
        "olaf_retells_red_riding_hood_medium_derailment",
        "olaf_retells_red_riding_hood_medium_adversarial",
        "olaf_retells_red_riding_hood_medium_targeted",
        "olaf_retells_red_riding_hood_complete_derailment",
        "olaf_retells_red_riding_hood_complete_adversarial",
        "olaf_retells_red_riding_hood_complete_targeted",
    ]
    short_labels = [
        "no\nderailment", "medium\nderailment", "medium\nadversarial", "medium\ntargeted",
        "complete\nderailment", "complete\nadversarial", "complete\ntargeted",
    ]
    a_vals = [per_scenario[s][0] for s in order]
    b_vals = [per_scenario[s][1] for s in order]

    x = range(len(order))
    width = 0.38
    fig, ax = plt.subplots(figsize=(11, 6.5))
    bars_a = ax.bar([i - width / 2 for i in x], a_vals, width, label=label_a, color=ORANGE)
    bars_b = ax.bar([i + width / 2 for i in x], b_vals, width, label=label_b, color=BLUE)
    for bars in (bars_a, bars_b):
        for rect in bars:
            h = rect.get_height()
            ax.annotate(f"{h:.1f}", (rect.get_x() + rect.get_width() / 2, h),
                        xytext=(0, 3), textcoords="offset points", ha="center", fontsize=10)
    ax.set_ylim(0, 11)
    ax.set_yticks(range(0, 11, 2))
    ax.set_ylabel("Overall judge score (0-10)")
    ax.set_xticks(list(x))
    ax.set_xticklabels(short_labels, fontsize=10)
    ax.set_title(f"{title}\n{subtitle}")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT_DIR / out_name, dpi=150)
    plt.close(fig)


def main():
    # Rocket: baseline vs director
    avg_a, avg_b, wins_a, wins_b, ties, per_scenario = load_rocket_bvd()
    n = len(per_scenario)
    grouped_bar_scores(
        avg_a, avg_b, "Baseline", "Director",
        "LLM-judge single-story scores: baseline vs. director (Rocket)",
        f"(n={n} Red Riding Hood derailment scenarios, GPT-4o judge)",
        "08_rocket_scores_by_metric.png",
    )
    stacked_pairwise_wins(
        wins_a, wins_b, ties, n, "Baseline", "Director",
        "Pairwise judge verdicts: baseline vs. director (Rocket)",
        "(order-bias controlled -- winner counted only if both AB and BA orders agree)",
        "09_rocket_pairwise_wins.png",
    )

    # Rocket: derailment level
    baseline_lv, director_lv = load_rocket_derailment()
    derailment_level_bar(
        baseline_lv, director_lv,
        "Rocket: score vs. derailment severity\nbaseline vs. director",
        "10_rocket_by_derailment_level.png",
    )

    # Beats vs full-text director
    avg_a2, avg_b2, wins_a2, wins_b2, ties2, per_scenario2 = load_beats_vs_fulltext()
    n2 = len(per_scenario2)
    grouped_bar_scores(
        avg_a2, avg_b2, "Beats", "Full text",
        "LLM-judge single-story scores: beats vs. full-text director",
        f"(n={n2} Red Riding Hood derailment scenarios, Olaf, GPT-4o judge)",
        "11_beats_vs_fulltext_scores_by_metric.png",
    )
    stacked_pairwise_wins(
        wins_a2, wins_b2, ties2, n2, "Beats", "Full text",
        "Pairwise judge verdicts: beats vs. full-text director",
        "(order-bias controlled -- winner counted only if both AB and BA orders agree)",
        "12_beats_vs_fulltext_pairwise_wins.png",
    )
    per_scenario_bar(
        per_scenario2, "Beats", "Full text",
        "Overall score per scenario: beats vs. full-text director",
        "(Olaf, Red Riding Hood derailment suite)",
        "13_beats_vs_fulltext_by_scenario.png",
    )

    print(f"Wrote plots to {OUT_DIR}")


if __name__ == "__main__":
    main()
