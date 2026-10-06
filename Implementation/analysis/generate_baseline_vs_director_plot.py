"""
analysis/generate_baseline_vs_director_plot.py

Regenerates all three baseline-vs-director figures from
evaluation_results/baseline_vs_director/*/eval_run_1.json:
    01_baseline_vs_director_scores_by_metric.png
    02_baseline_vs_director_pairwise_wins.png
    03_baseline_vs_director_by_derailment_level.png

Scoped to the original n=33 scenario x derailment-level transcripts (same set
used to first render these plots): excludes the rocket_* character comparison
and the olaf_retells_cinderella_* / olaf_retells_frozen_1_* scenarios, which
are separate evaluation efforts not part of these figures.

To change a title, edit the TITLE_* constants below and re-run.

Usage (from Implementation/):
    python analysis/generate_baseline_vs_director_plot.py
"""

import json
import glob
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT_DIR = Path(__file__).parent.parent / "evaluation_summary" / "plots"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_NAME = "01_baseline_vs_director_scores_by_metric.png"
OUT_NAME_WINS = "02_baseline_vs_director_pairwise_wins.png"
OUT_NAME_DERAIL = "03_baseline_vs_director_by_derailment_level.png"

EXCLUDE_PREFIXES = ("rocket_", "olaf_retells_cinderella", "olaf_retells_frozen_1")

TITLE = "LLM-judge single-story scores: baseline vs. director"
TITLE_WINS = "Pairwise judge verdicts: baseline vs. director"
SUBTITLE_WINS = "(order-bias controlled -- winner counted only if both AB and BA orders agree)"

METRICS = [
    "Plot",
    "Development",
    "Language Use",
    "Interruption Handling",
    "Character Fidelity",
    "Narrative Control",
    "Anthropomorphism",
    "Overall",
]
METRIC_LABELS = [m.replace(" ", "\n") for m in METRICS]

BLUE = "#4c72b0"
ORANGE = "#dd8452"
GRAY = "#d3d3d3"

plt.rcParams["font.size"] = 14


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_baseline_vs_director():
    paths = sorted(glob.glob("evaluation_results/baseline_vs_director/*/eval_run_1.json"))
    paths = [
        p for p in paths if not any(Path(p).parent.name.startswith(pfx) for pfx in EXCLUDE_PREFIXES)
    ]

    sum_a, sum_b, n_a, n_b = (
        defaultdict(float),
        defaultdict(float),
        defaultdict(int),
        defaultdict(int),
    )
    for p in paths:
        d = load(p)
        a = d["single_story_scores"]["A"]["scores"]
        b = d["single_story_scores"]["B"]["scores"]
        for m in METRICS:
            if a.get(m) is not None:
                sum_a[m] += a[m]
                n_a[m] += 1
            if b.get(m) is not None:
                sum_b[m] += b[m]
                n_b[m] += 1

    avg_a = {m: sum_a[m] / n_a[m] for m in METRICS if n_a[m]}
    avg_b = {m: sum_b[m] / n_b[m] for m in METRICS if n_b[m]}
    return avg_a, avg_b, len(paths)


def _filtered_paths():
    paths = sorted(glob.glob("evaluation_results/baseline_vs_director/*/eval_run_1.json"))
    return [
        p for p in paths if not any(Path(p).parent.name.startswith(pfx) for pfx in EXCLUDE_PREFIXES)
    ]


LEGACY_RRH_NAMES = (
    "complete_derail_red_riding_hood",
    "medium_derail_red_riding_hood",
    "noderail_red_riding_hood",
)


def load_pairwise_wins():
    # Excludes the 3 legacy Red Riding Hood pilot scenarios (pre-dating the
    # olaf_derailment_scenario_suite) to match the n=30 scope used everywhere
    # else in this thesis (the CoDi comparison, the time-budget ablation) --
    # leaving the 33-scenario set as the odd one out otherwise.
    paths = [p for p in _filtered_paths() if Path(p).parent.name not in LEGACY_RRH_NAMES]
    wins_a, wins_b, ties = defaultdict(int), defaultdict(int), defaultdict(int)
    for p in paths:
        d = load(p)
        for m, w in d.get("aggregated_ab_ba_winners", {}).items():
            if m not in METRICS:
                continue
            if w == "A":
                wins_a[m] += 1
            elif w == "B":
                wins_b[m] += 1
            else:
                ties[m] += 1
    return wins_a, wins_b, ties, len(paths)


def load_by_derailment_level(metric="Overall"):
    paths = _filtered_paths()

    def level(name):
        if "complete" in name:
            return "Complete"
        if "medium" in name:
            return "Medium"
        return "None"

    sum_a, sum_b, n = defaultdict(float), defaultdict(float), defaultdict(int)
    for p in paths:
        name = Path(p).parent.name
        d = load(p)
        a = d["single_story_scores"]["A"]["scores"][metric]
        b = d["single_story_scores"]["B"]["scores"][metric]
        lv = level(name)
        sum_a[lv] += a
        sum_b[lv] += b
        n[lv] += 1

    baseline = {lv: sum_a[lv] / n[lv] for lv in n}
    director = {lv: sum_b[lv] / n[lv] for lv in n}
    return baseline, director


def plot(avg_a, avg_b):
    x = range(len(METRICS))
    width = 0.38
    fig, ax = plt.subplots(figsize=(13, 6.5))
    bars_a = ax.bar(
        [i - width / 2 for i in x],
        [avg_a[m] for m in METRICS],
        width,
        label="Baseline",
        color=ORANGE,
    )
    bars_b = ax.bar(
        [i + width / 2 for i in x], [avg_b[m] for m in METRICS], width, label="Director", color=BLUE
    )
    for bars in (bars_a, bars_b):
        for rect in bars:
            h = rect.get_height()
            ax.annotate(
                f"{h:.1f}",
                (rect.get_x() + rect.get_width() / 2, h),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                fontsize=13,
            )
    ax.set_ylim(0, 11)
    ax.set_yticks(range(0, 11, 2))
    ax.set_ylabel("Mean judge score (0-10)", fontsize=14)
    ax.set_xticks(list(x))
    ax.set_xticklabels(METRIC_LABELS, fontsize=13)
    ax.tick_params(axis="y", labelsize=13)
    ax.set_title(TITLE, fontsize=16)
    ax.legend(fontsize=13)
    fig.tight_layout()
    fig.savefig(OUT_DIR / OUT_NAME, dpi=150)
    plt.close(fig)


def plot_pairwise_wins(wins_a, wins_b, ties, n):
    x = range(len(METRICS))
    a_vals = [wins_a[m] for m in METRICS]
    tie_vals = [ties[m] for m in METRICS]
    b_vals = [wins_b[m] for m in METRICS]

    fig, ax = plt.subplots(figsize=(13, 7.5))
    ax.bar(x, a_vals, color=ORANGE, label="Baseline wins")
    ax.bar(x, tie_vals, bottom=a_vals, color=GRAY, label="Tie")
    bottoms2 = [a + t for a, t in zip(a_vals, tie_vals)]
    ax.bar(x, b_vals, bottom=bottoms2, color=BLUE, label="Director wins")

    for i in x:
        cum = 0
        for val, color in ((a_vals[i], "white"), (tie_vals[i], "black"), (b_vals[i], "white")):
            if val > 0:
                ax.text(
                    i, cum + val / 2, str(val), ha="center", va="center", color=color, fontsize=12
                )
            cum += val

    ax.set_xticks(list(x))
    ax.set_xticklabels(METRIC_LABELS, fontsize=13)
    ax.tick_params(axis="y", labelsize=13)
    ax.set_ylabel(f"Number of scenario comparisons (of {n})", fontsize=14)
    ax.set_title(f"{TITLE_WINS}\n{SUBTITLE_WINS}", fontsize=15)
    ax.legend(fontsize=13, loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=3, frameon=False)
    fig.tight_layout()
    fig.savefig(OUT_DIR / OUT_NAME_WINS, dpi=150)
    plt.close(fig)


def plot_by_derailment_level(baseline, director, metric="Overall", title=None, out_name=None):
    levels = ["None", "Medium", "Complete"]
    x = range(len(levels))
    width = 0.35
    fig, ax = plt.subplots(figsize=(7, 6.5))
    bars_a = ax.bar(
        [i - width / 2 for i in x],
        [baseline[lvl] for lvl in levels],
        width,
        label="Baseline",
        color=ORANGE,
    )
    bars_b = ax.bar(
        [i + width / 2 for i in x],
        [director[lvl] for lvl in levels],
        width,
        label="Director",
        color=BLUE,
    )
    for bars in (bars_a, bars_b):
        for rect in bars:
            h = rect.get_height()
            ax.annotate(
                f"{h:.2f}",
                (rect.get_x() + rect.get_width() / 2, h),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                fontsize=12,
            )
    ax.set_ylim(0, 10.8)
    ax.set_ylabel(f"Mean {metric} score (0-10)", fontsize=14)
    ax.set_xlabel("Derailment level in scenario", fontsize=14)
    ax.set_xticks(list(x))
    ax.set_xticklabels(levels, fontsize=13)
    ax.tick_params(axis="y", labelsize=13)
    ax.set_title(
        title or f"{metric} score vs. derailment severity,\nbaseline vs. director", fontsize=14
    )
    ax.legend(fontsize=12)
    fig.tight_layout()
    fig.savefig(OUT_DIR / (out_name or OUT_NAME_DERAIL), dpi=150)
    plt.close(fig)


def main():
    avg_a, avg_b, n = load_baseline_vs_director()
    print(f"Scenarios included: {n}")
    plot(avg_a, avg_b)
    print(f"Saved: {OUT_DIR / OUT_NAME}")

    wins_a, wins_b, ties, n_wins = load_pairwise_wins()
    plot_pairwise_wins(wins_a, wins_b, ties, n_wins)
    print(f"Saved: {OUT_DIR / OUT_NAME_WINS}")

    baseline_lv, director_lv = load_by_derailment_level("Overall")
    plot_by_derailment_level(baseline_lv, director_lv)
    print(f"Saved: {OUT_DIR / OUT_NAME_DERAIL}")

    baseline_nc, director_nc = load_by_derailment_level("Narrative Control")
    plot_by_derailment_level(
        baseline_nc,
        director_nc,
        metric="Narrative Control",
        title="Narrative Control score vs. derailment severity,\nbaseline vs. director",
        out_name="16_narrative_control_by_derailment_level.png",
    )
    print(f"Saved: {OUT_DIR / '16_narrative_control_by_derailment_level.png'}")

    baseline_ih, director_ih = load_by_derailment_level("Interruption Handling")
    plot_by_derailment_level(
        baseline_ih,
        director_ih,
        metric="Interruption Handling",
        title="Interruption Handling score vs. derailment severity,\nbaseline vs. director",
        out_name="17_interruption_handling_by_derailment_level.png",
    )
    print(f"Saved: {OUT_DIR / '17_interruption_handling_by_derailment_level.png'}")


if __name__ == "__main__":
    main()
