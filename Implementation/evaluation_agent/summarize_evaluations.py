"""
evaluation_agent/summarize_evaluations.py

Summarizes all pairwise evaluation JSON files and produces pivot tables.

Each evaluation JSON compares two stories (A and B):
    - story_a_path / story_b_path  -> method and scenario encoded in the path
    - single_story_scores.A.scores / .B.scores -> per-metric scores (0-10)
    - aggregated_ab_ba_winners -> counterbalanced pairwise winner per metric

Adding a new scenario or method automatically creates new rows/columns.

Outputs in --output_dir (default: evaluation_summary/):
    all_runs_flat.csv
    table_scores_by_metric.{csv,md,tex}
    table_scores_by_scenario.{csv,md,tex}
    table_derailment_robustness.{csv,md,tex}
    table_pairwise_wins.{csv,md,tex}

Usage (run from Implementation/):
    python evaluation_agent/summarize_evaluations.py
    python evaluation_agent/summarize_evaluations.py \\
        --input_dir evaluation_results \\
        --output_dir evaluation_summary
"""

import json
import argparse
from pathlib import Path

import pandas as pd

METRICS = [
    "Plot",
    "Development",
    "Language Use",
    "Interruption Handling",
    "Character Fidelity",
    "Narrative Control",
    "Overall",
]

METHOD_ORDER = ["baseline", "codi", "director", "time_constrained"]
DERAILMENT_ORDER = ["none", "medium", "complete"]


# ──────────────────────────────────────────────────────────────────────────────
# Path parsing
# ──────────────────────────────────────────────────────────────────────────────

_METHOD_MAP = {
    "baseline": "baseline",
    "director_agent": "director",
    "target_duration_director_agent": "time_constrained",
    "codi": "codi",
}


def parse_story_path(path_str: str) -> dict:
    """
    Extract method, scenario, and time_limit from a story output path.

    Handles path variants produced by different runner scripts:
        outputs/baseline/<scenario>/batch/run_N.json
        outputs/director_agent/<scenario>/batch/run_N.json
        outputs/target_duration_director_agent/<scenario>/<time>min/batch/run_N.json
        outputs/codi/<scenario>/batch/run_N.json
        outputs/codi_<scenario>.json          (legacy filename-encoded codi)
        Implementation/outputs/...            (with repo-root prefix)
    """
    path = path_str.replace("\\", "/")
    for prefix in ("Implementation/", "./Implementation/"):
        if path.startswith(prefix):
            path = path[len(prefix):]

    parts = [p for p in path.split("/") if p]

    _unknown = {"method": "unknown", "scenario": "unknown", "time_limit": None}

    if not parts or parts[0] != "outputs":
        return _unknown

    parts = parts[1:]

    if not parts:
        return _unknown

    method_raw = parts[0]

    # Legacy: "codi_<scenario>.json" was placed directly under outputs/
    if method_raw.startswith("codi_"):
        scenario = method_raw.removesuffix(".json")[len("codi_"):]
        return {"method": "codi", "scenario": scenario, "time_limit": None}

    scenario = parts[1] if len(parts) > 1 else "unknown"

    time_limit = None
    if method_raw == "target_duration_director_agent" and len(parts) >= 3:
        candidate = parts[2]
        if candidate.endswith("min"):
            time_limit = candidate

    method = _METHOD_MAP.get(method_raw, method_raw)
    return {"method": method, "scenario": scenario, "time_limit": time_limit}


def _method_display(meta: dict) -> str:
    if meta["time_limit"]:
        return f"time_constrained ({meta['time_limit']})"
    return meta["method"]


def infer_derailment(scenario: str) -> str:
    s = scenario.lower()
    if "complete_derail" in s:
        return "complete"
    if "medium_derail" in s:
        return "medium"
    if "noderail" in s or "no_derailment" in s:
        return "none"
    return "unknown"


def infer_base_scenario(scenario: str) -> str:
    for suffix in ("_complete_derailment", "_medium_derailment", "_no_derailment"):
        if scenario.endswith(suffix):
            return scenario[: -len(suffix)]
    for prefix in ("complete_derail_", "medium_derail_", "noderail_"):
        if scenario.startswith(prefix):
            return scenario[len(prefix):]
    return scenario


# ──────────────────────────────────────────────────────────────────────────────
# Loading
# ──────────────────────────────────────────────────────────────────────────────

def load_evaluation_files(input_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Scan input_dir recursively for evaluation JSON files.

    Returns
    -------
    scores_df : one row per story per file (method, scenario, metric scores)
    wins_df   : one row per (file, metric) with the pairwise winner
    """
    score_rows = []
    win_rows = []

    json_files = sorted(input_dir.rglob("*.json"))
    if not json_files:
        raise FileNotFoundError(f"No JSON files found under {input_dir}")

    loaded = 0
    for path in json_files:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        if "single_story_scores" not in data:
            continue

        loaded += 1
        meta_a = parse_story_path(data.get("story_a_path", ""))
        meta_b = parse_story_path(data.get("story_b_path", ""))

        # Both sides should be the same scenario; use A's as canonical
        scenario = meta_a["scenario"]
        derailment = infer_derailment(scenario)
        base_scenario = infer_base_scenario(scenario)

        for label, meta in (("A", meta_a), ("B", meta_b)):
            scores = data["single_story_scores"].get(label, {}).get("scores", {})
            if not scores:
                continue
            row = {
                "file": str(path),
                "method": _method_display(meta),
                "scenario": scenario,
                "base_scenario": base_scenario,
                "derailment_level": derailment,
            }
            for m in METRICS:
                row[m] = scores.get(m)
            score_rows.append(row)

        winners = data.get("aggregated_ab_ba_winners")
        if winners:
            disp_a = _method_display(meta_a)
            disp_b = _method_display(meta_b)
            pair = f"{disp_a} vs {disp_b}"
            for metric, winner_label in winners.items():
                if metric not in METRICS:
                    continue
                winner_method = (
                    disp_a if winner_label == "A"
                    else disp_b if winner_label == "B"
                    else "Same"
                )
                win_rows.append({
                    "file": str(path),
                    "scenario": scenario,
                    "base_scenario": base_scenario,
                    "derailment_level": derailment,
                    "pair": pair,
                    "method_a": disp_a,
                    "method_b": disp_b,
                    "metric": metric,
                    "winner": winner_method,
                })

    if loaded == 0:
        raise ValueError(
            f"Found {len(json_files)} JSON file(s) under {input_dir} "
            "but none contained 'single_story_scores'. "
            "Check that --input_dir points to evaluation result files."
        )

    scores_df = pd.DataFrame(score_rows)
    wins_df = pd.DataFrame(win_rows)

    for m in METRICS:
        if m in scores_df.columns:
            scores_df[m] = pd.to_numeric(scores_df[m], errors="coerce")

    return scores_df, wins_df


# ──────────────────────────────────────────────────────────────────────────────
# Table builders
# ──────────────────────────────────────────────────────────────────────────────

def _ordered_index(index):
    ordered = [m for m in METHOD_ORDER if m in index]
    others = sorted(m for m in index if m not in ordered)
    return ordered + others


def make_scores_by_metric(scores_df: pd.DataFrame) -> pd.DataFrame:
    """rows = method | cols = metric | values = mean score across all scenarios/runs."""
    present = [m for m in METRICS if m in scores_df.columns]
    table = scores_df.groupby("method")[present].mean().round(2)
    return table.loc[_ordered_index(table.index)]


def make_scores_by_scenario(scores_df: pd.DataFrame) -> pd.DataFrame:
    """rows = method | cols = base_scenario | values = mean Overall score."""
    table = pd.pivot_table(
        scores_df,
        index="method",
        columns="base_scenario",
        values="Overall",
        aggfunc="mean",
    ).round(2)
    table.columns.name = None
    return table.loc[_ordered_index(table.index)]


def make_derailment_robustness(scores_df: pd.DataFrame) -> pd.DataFrame:
    """rows = method | cols = derailment level | values = mean Overall score."""
    table = pd.pivot_table(
        scores_df,
        index="method",
        columns="derailment_level",
        values="Overall",
        aggfunc="mean",
    ).round(2)
    table.columns.name = None
    ordered_cols = [c for c in DERAILMENT_ORDER if c in table.columns]
    other_cols = [c for c in table.columns if c not in ordered_cols]
    table = table[ordered_cols + other_cols]
    return table.loc[_ordered_index(table.index)]


def make_pairwise_wins(wins_df: pd.DataFrame) -> pd.DataFrame:
    """
    rows = comparison pair (e.g. 'baseline vs director')
    cols = metric
    values = "MethodA: N | MethodB: M | Tie: T"
    """
    if wins_df.empty:
        return pd.DataFrame()

    summary_rows = []
    for (pair, metric), group in wins_df.groupby(["pair", "metric"]):
        method_a = group["method_a"].iloc[0]
        method_b = group["method_b"].iloc[0]
        a_wins = (group["winner"] == method_a).sum()
        b_wins = (group["winner"] == method_b).sum()
        ties = (group["winner"] == "Same").sum()
        summary_rows.append({
            "pair": pair,
            "metric": metric,
            "summary": f"{method_a}: {a_wins} | {method_b}: {b_wins} | Tie: {ties}",
        })

    df = pd.DataFrame(summary_rows)
    table = df.pivot(index="pair", columns="metric", values="summary")
    table.columns.name = None
    metric_order = [m for m in METRICS if m in table.columns]
    return table[metric_order]


# ──────────────────────────────────────────────────────────────────────────────
# Output helpers
# ──────────────────────────────────────────────────────────────────────────────

def save_table(table: pd.DataFrame, output_dir: Path, name: str):
    table.to_csv(output_dir / f"{name}.csv")
    table.to_markdown(output_dir / f"{name}.md")
    table.to_latex(output_dir / f"{name}.tex", float_format="%.2f")
    print(f"  {name}.{{csv,md,tex}}")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Summarize pairwise evaluation results into pivot tables."
    )
    parser.add_argument(
        "--input_dir",
        default="evaluation_results",
        help="Directory containing evaluation JSON files (searched recursively).",
    )
    parser.add_argument(
        "--output_dir",
        default="evaluation_summary",
        help="Directory where summary tables will be written.",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading from {input_dir} ...")
    scores_df, wins_df = load_evaluation_files(input_dir)

    scores_df.to_csv(output_dir / "all_runs_flat.csv", index=False)
    print(f"  all_runs_flat.csv  ({len(scores_df)} story records from {scores_df['file'].nunique()} files)")

    print("\nGenerating tables ...")
    save_table(make_scores_by_metric(scores_df), output_dir, "table_scores_by_metric")
    save_table(make_scores_by_scenario(scores_df), output_dir, "table_scores_by_scenario")
    save_table(make_derailment_robustness(scores_df), output_dir, "table_derailment_robustness")

    if not wins_df.empty:
        save_table(make_pairwise_wins(wins_df), output_dir, "table_pairwise_wins")
    else:
        print("  (no pairwise win data found)")

    print("\nSummary:")
    print(f"  Methods found:    {sorted(scores_df['method'].unique())}")
    print(f"  Base scenarios:   {sorted(scores_df['base_scenario'].unique())}")
    print(f"  Derailment levels:{sorted(scores_df['derailment_level'].unique())}")


if __name__ == "__main__":
    main()
