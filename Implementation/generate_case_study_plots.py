"""
generate_case_study_plots.py

Plots for the thesis case-study section comparing the LLM judge against the
live user study, for the exact two stories participants played (Frozen,
Cinderella), using the complete-derailment scenario variant -- the automated
scenario closest to what live participants actually did, since the welcome
screen explicitly incentivized them to try to derail the story every round.

Values are the mean of 5 independent generate+judge runs per condition (see
regen_case_study_5x.py and evaluation_results/case_study_5x_results.json),
not a single transcript. Director was regenerated fresh for all 5 runs on
both scenarios since the previously-used run_1 predated the director_core.py
pacing fix; baseline and the 5-minute time-constrained run reuse existing
run_1 where present and only generate runs 2-5 fresh.
Some individual runs still needed score recovery by hand from the raw judge
assessment text, because evaluation_core.py's score parser does not match the judge's
"**Dimension:**\\nScore: X / 10" formatting (see thesis note on this bug).

Usage (from Implementation/):
    python generate_case_study_plots.py
"""

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
GREEN = "#55a868"

plt.rcParams["font.size"] = 14

# olaf_retells_frozen_1_complete_derailment, baseline vs director
FROZEN_BASELINE = {"Plot": 3.44, "Development": 4.15, "Language Use": 8.82, "Interruption Handling": 3.88,
                   "Character Fidelity": 8.42, "Narrative Control": 3.12, "Anthropomorphism": 6.55, "Overall": 5.48}

FROZEN_DIRECTOR = {"Plot": 8.74, "Development": 8.54, "Language Use": 8.62, "Interruption Handling": 8.89,
                   "Character Fidelity": 8.51, "Narrative Control": 8.54, "Anthropomorphism": 8.86, "Overall": 8.67}

# olaf_retells_cinderella_complete_derailment (mean of 5 runs each)
CINDERELLA_DIRECTOR = {"Plot": 8.65, "Development": 8.61, "Language Use": 8.89, "Interruption Handling": 8.75,
                       "Character Fidelity": 8.56, "Narrative Control": 8.62, "Anthropomorphism": 9.12, "Overall": 8.74}

CINDERELLA_5MIN = {"Plot": 8.19, "Development": 7.45, "Language Use": 8.65, "Interruption Handling": 8.82,
                   "Character Fidelity": 8.82, "Narrative Control": 8.42, "Anthropomorphism": 8.96, "Overall": 8.47}



def two_bar_plot(scores_a, scores_b, label_a, label_b, title, out_name, color_a=ORANGE, color_b=BLUE):
    x = range(len(METRICS))
    width = 0.38
    fig, ax = plt.subplots(figsize=(13, 6.5))
    bars_a = ax.bar([i - width / 2 for i in x], [scores_a[m] for m in METRICS], width, label=label_a, color=color_a)
    bars_b = ax.bar([i + width / 2 for i in x], [scores_b[m] for m in METRICS], width, label=label_b, color=color_b)
    for bars in (bars_a, bars_b):
        for rect in bars:
            h = rect.get_height()
            ax.annotate(f"{h:.1f}", (rect.get_x() + rect.get_width() / 2, h),
                        xytext=(0, 3), textcoords="offset points", ha="center", fontsize=13)
    ax.set_ylim(0, 11.2)
    ax.set_yticks(range(0, 11, 2))
    ax.set_ylabel("Judge score (0-10)", fontsize=14)
    ax.set_xticks(list(x))
    ax.set_xticklabels(METRIC_LABELS, fontsize=13)
    ax.tick_params(axis="y", labelsize=13)
    ax.set_title(title, fontsize=16)
    ax.legend(fontsize=13)
    fig.tight_layout()
    fig.savefig(OUT_DIR / out_name, dpi=150)
    plt.close(fig)


def main():
    two_bar_plot(
        FROZEN_BASELINE, FROZEN_DIRECTOR, "Baseline", "Director",
        "Frozen (complete derailment): judge score, mean of 5 runs, baseline vs. director",
        "14_frozen_case_study_complete_derailment.png",
    )
    two_bar_plot(
        CINDERELLA_DIRECTOR, CINDERELLA_5MIN, "Director", "5 min (time-constrained)",
        "Cinderella (complete derailment): judge score, mean of 5 runs, director vs. time-constrained",
        "15_cinderella_case_study_complete_derailment.png",
        color_a=BLUE, color_b=GREEN,
    )
    print("Saved 14_frozen_case_study_complete_derailment.png and 15_cinderella_case_study_complete_derailment.png")


if __name__ == "__main__":
    main()
