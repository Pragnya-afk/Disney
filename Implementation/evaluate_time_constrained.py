"""
evaluate_time_constrained.py

Comprehensive evaluation of time-constrained director-agent outputs.

Compares outputs at 0.5 min, 2.0 min, 5.0 min, and 10.0 min against each
other and (optionally) against the unconstrained director-agent reference.

Stages
------
  quant   Compute structural/efficiency metrics from transcript JSON files (no LLM).
  qual    Run LLM qualitative single-story scoring on each time-limited output.
  sim     Compute pairwise cosine similarity across time limits using OpenAI embeddings.
  tables  Aggregate results into CSV/Markdown summary tables.

All stages run by default. Use --only to run a subset.

Outputs
-------
  evaluation_results/time_constrained/{scenario}/quantitative_metrics.json
  evaluation_results/time_constrained/{scenario}/qualitative_scores.json
  evaluation_results/time_constrained/{scenario}/cosine_similarity.json
  evaluation_summary/time_constrained_quantitative.{csv,md}
  evaluation_summary/time_constrained_qualitative.{csv,md}
  evaluation_summary/time_constrained_similarity.{csv,md}

Usage (run from Implementation/):
    python evaluate_time_constrained.py
    python evaluate_time_constrained.py --dry-run
    python evaluate_time_constrained.py --only quant
    python evaluate_time_constrained.py --only qual --model gpt-4o
    python evaluate_time_constrained.py --only tables
    python evaluate_time_constrained.py --scenario olaf_arendelle_tour_no_derailment
    python evaluate_time_constrained.py --force
"""

import os
import sys
import re
import json
import argparse
from datetime import datetime
from pathlib import Path
from statistics import mean, stdev

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CURRENT_DIR)
sys.path.insert(0, os.path.join(CURRENT_DIR, "evaluation_agent"))

from dotenv import load_dotenv
load_dotenv(os.path.join(CURRENT_DIR, ".env"))

TIME_LIMITS = ["0.5min", "2.0min", "5.0min", "10.0min"]
TC_OUTPUTS_DIR = Path(CURRENT_DIR) / "outputs" / "target_duration_director_agent"
DIRECTOR_OUTPUTS_DIR = Path(CURRENT_DIR) / "outputs" / "director_agent"
EVAL_TC_DIR = Path(CURRENT_DIR) / "evaluation_results" / "time_constrained"
SUMMARY_DIR = Path(CURRENT_DIR) / "evaluation_summary"

DEFAULT_MODEL = "gpt-4o"
DEFAULT_RUN_ID = 1

QUAL_DIMENSIONS = [
    "Descriptiveness",
    "Beat Fidelity",
    "Transition Quality",
    "Character Voice",
    "Three-Act Balance",
    "Setup/Payoff Preservation",
    "Emotional Arc",
    "Overall",
]



def discover_scenarios(filter_name: str | None) -> list[dict]:
    """Return list of scenario dicts with available time-limit paths."""
    if not TC_OUTPUTS_DIR.exists():
        return []

    scenarios = []
    for sc_dir in sorted(TC_OUTPUTS_DIR.iterdir()):
        if not sc_dir.is_dir():
            continue
        if filter_name and sc_dir.name != filter_name:
            continue

        time_paths = {}
        for tl in TIME_LIMITS:
            p = sc_dir / tl / "batch" / f"run_{DEFAULT_RUN_ID}.json"
            if p.exists():
                time_paths[tl] = p

        if not time_paths:
            continue

        director_path = DIRECTOR_OUTPUTS_DIR / sc_dir.name / "batch" / f"run_{DEFAULT_RUN_ID}.json"

        scenarios.append({
            "scenario_name": sc_dir.name,
            "time_paths": time_paths,
            "director_path": director_path if director_path.exists() else None,
        })

    return scenarios


def load_scenario_beats(scenario_name: str) -> list[dict]:
    """Try to load beat list from the scenario suite."""
    try:
        from scenarios.olaf_derailment_scenario_suite import SCENARIOS
        if scenario_name in SCENARIOS:
            return SCENARIOS[scenario_name]["beats"]
    except ImportError:
        pass

    # Try individual scenario modules
    import importlib
    try:
        mod = importlib.import_module(f"scenarios.{scenario_name}")
        return mod.SCENARIO["beats"]
    except (ImportError, AttributeError):
        pass

    return []



def load_json(path: Path) -> list:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_character_response(turn: dict) -> str:
    output = turn.get("actor_output") or turn.get("model_output", {})
    return output.get("character_response", "")


def get_beat_completed(turn: dict) -> bool:
    output = turn.get("actor_output") or turn.get("model_output", {})
    return bool(output.get("beat_completed"))


def transcript_to_full_text(transcript: list) -> str:
    return " ".join(get_character_response(t) for t in transcript).strip()


def transcript_to_story_text(transcript: list) -> str:
    """Convert transcript to evaluator-readable text (mirrors evaluation_core)."""
    lines = []
    for i, turn in enumerate(transcript, start=1):
        beat = turn.get("beat", "unknown_beat")
        user_input = turn.get("user_input", "")
        lines.append(f"Turn {i} | Beat: {beat}")
        lines.append(f"User: {user_input}")

        if "actor_output" in turn:
            dd = turn.get("director_decision", {})
            ao = turn["actor_output"]
            lines.append(f"Director Decision: {dd.get('decision_type', '')}")
            lines.append(f"Director Instruction: {dd.get('director_instruction', '')}")
            lines.append(f"Character: {ao.get('character_response', '')}")
            lines.append(f"Story Event: {ao.get('story_event', '')}")
            lines.append(f"Beat Completed: {ao.get('beat_completed', False)}")
        elif "model_output" in turn:
            mo = turn["model_output"]
            lines.append(f"Character: {mo.get('character_response', '')}")
            lines.append(f"Story Event: {mo.get('story_event', '')}")
            lines.append(f"Beat Completed: {mo.get('beat_completed', False)}")

        lines.append("")

    return "\n".join(lines).strip()



def compute_quantitative_metrics(transcript: list, beats: list) -> dict:
    """Compute structural and efficiency metrics from a transcript."""
    if not transcript:
        return {}

    total_beats = len(beats)
    beat_name_set = {b["name"] for b in beats}
    final_beat_name = beats[-1]["name"] if beats else ""

    # Beats seen (ordered) and covered
    beats_seen_ordered = list(dict.fromkeys(t["beat"] for t in transcript))
    beats_covered = len([b for b in beats_seen_ordered if b in beat_name_set])

    # Beats completed by flag
    completed_beat_names: set[str] = set()
    for turn in transcript:
        if get_beat_completed(turn) and turn["beat"] not in completed_beat_names:
            completed_beat_names.add(turn["beat"])
    beats_completed = len(completed_beat_names)

    # Beats skipped (expected but never seen)
    expected = [b["name"] for b in beats]
    seen_set = set(t["beat"] for t in transcript)
    beats_skipped = len([b for b in expected if b not in seen_set])

    # Beat merge rate: beats present in scenario but absent from transcript
    # (a beat is "merged" if it was skipped but story still progressed)
    # We approximate: if we covered fewer beats than total but did reach later ones
    beat_merge_rate = beats_skipped / total_beats if total_beats else 0.0

    # Word counts per turn
    word_counts = [len(get_character_response(t).split()) for t in transcript]
    total_words = sum(word_counts)
    words_per_beat = total_words / max(beats_covered, 1)

    pacing_variance = (
        stdev(word_counts) if len(word_counts) > 1 else 0.0
    )

    # Truncation detection
    last_turn = transcript[-1]
    last_beat_name = last_turn.get("beat", "")
    last_beat_is_final = last_beat_name == final_beat_name
    last_turn_completed = get_beat_completed(last_turn)
    truncated = not (last_beat_is_final and last_turn_completed)

    # Timing from temporal_state (available in time-constrained transcripts)
    elapsed_seconds = 0.0
    for turn in reversed(transcript):
        ts = turn.get("temporal_state", {})
        if ts.get("elapsed_seconds"):
            elapsed_seconds = ts["elapsed_seconds"]
            break

    approx_tokens = total_words * 1.3
    tokens_per_second = (
        round(approx_tokens / elapsed_seconds, 2) if elapsed_seconds > 0 else None
    )

    return {
        "scene_count": len(transcript),
        "total_beats": total_beats,
        "beats_covered": beats_covered,
        "beat_cover_rate": round(beats_covered / total_beats, 3) if total_beats else 0.0,
        "beats_completed_by_flag": beats_completed,
        "beat_completion_rate": round(beats_completed / total_beats, 3) if total_beats else 0.0,
        "beats_skipped": beats_skipped,
        "beat_merge_rate": round(beat_merge_rate, 3),
        "total_words": total_words,
        "words_per_beat": round(words_per_beat, 1),
        "pacing_variance": round(pacing_variance, 2),
        "truncated": truncated,
        "elapsed_seconds": round(elapsed_seconds, 1),
        "approx_tokens_per_second": tokens_per_second,
    }


def run_quant_stage(scenario: dict, force: bool) -> dict | None:
    """Compute and save quantitative metrics for all time limits."""
    scenario_name = scenario["scenario_name"]
    out_dir = EVAL_TC_DIR / scenario_name
    out_path = out_dir / "quantitative_metrics.json"

    if out_path.exists() and not force:
        print(f"  [quant] skip (exists): {scenario_name}")
        return json.loads(out_path.read_text())

    beats = load_scenario_beats(scenario_name)
    if not beats:
        print(f"  [quant] WARNING: no beats found for {scenario_name}, metrics will use 0 as total.")

    result = {
        "scenario": scenario_name,
        "total_beats": len(beats),
        "time_limits": {},
    }

    for tl, path in scenario["time_paths"].items():
        transcript = load_json(path)
        metrics = compute_quantitative_metrics(transcript, beats)
        result["time_limits"][tl] = metrics
        print(f"  [quant] {scenario_name} / {tl}: {metrics['scene_count']} turns, "
              f"{metrics['beats_covered']}/{metrics['total_beats']} beats, "
              f"{metrics['total_words']} words")

    # Also compute for director reference if available
    if scenario["director_path"]:
        transcript = load_json(scenario["director_path"])
        metrics = compute_quantitative_metrics(transcript, beats)
        result["time_limits"]["director"] = metrics
        print(f"  [quant] {scenario_name} / director: {metrics['scene_count']} turns, "
              f"{metrics['beats_covered']}/{metrics['total_beats']} beats")

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"  [quant] saved → {out_path}")
    return result



def parse_time_constrained_scores(assessment: str) -> dict:
    """Parse 'Dimension: N / 5' lines from the evaluator response."""
    scores = {}
    for dim in QUAL_DIMENSIONS:
        pattern = rf"{re.escape(dim)}:\s*([0-9]+(?:\.[0-9]+)?)\s*/\s*5"
        match = re.search(pattern, assessment, re.IGNORECASE)
        scores[dim] = float(match.group(1)) if match else None
    return scores


def build_character_profile_for_scenario(scenario_name: str) -> str:
    try:
        from character_prompts.olaf import CHARACTER
    except ImportError:
        CHARACTER = {"name": "Olaf", "character_prompt": "", "available_animations": []}

    beats = load_scenario_beats(scenario_name)

    story_topic = ""
    try:
        from scenarios.olaf_derailment_scenario_suite import SCENARIOS
        if scenario_name in SCENARIOS:
            story_topic = SCENARIOS[scenario_name].get("story_topic", "")
    except ImportError:
        pass

    payload = {
        "character": CHARACTER,
        "story_topic": story_topic,
        "beats": beats,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def run_qual_stage(scenario: dict, model: str, force: bool) -> dict | None:
    """Run LLM qualitative scoring for each time limit."""
    from openai import OpenAI

    scenario_name = scenario["scenario_name"]
    out_dir = EVAL_TC_DIR / scenario_name
    out_path = out_dir / "qualitative_scores.json"

    if out_path.exists() and not force:
        print(f"  [qual] skip (exists): {scenario_name}")
        return json.loads(out_path.read_text())

    from evaluation_agent.evaluation_prompts_time import EVALUATE_TIME_CONSTRAINED_QUALITY_PROMPT

    client = OpenAI()
    character_profile = build_character_profile_for_scenario(scenario_name)

    result = {
        "scenario": scenario_name,
        "model": model,
        "time_limits": {},
    }

    targets = dict(scenario["time_paths"])
    if scenario["director_path"]:
        targets["director"] = scenario["director_path"]

    for label, path in targets.items():
        transcript = load_json(path)
        story_text = transcript_to_story_text(transcript)

        prompt = EVALUATE_TIME_CONSTRAINED_QUALITY_PROMPT.format(
            character_profile=character_profile,
            story=story_text,
        )

        print(f"  [qual] scoring {scenario_name} / {label}…")
        response = client.chat.completions.create(
            model=model,
            temperature=0.0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a careful literary critic evaluating interactive AI character stories."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        assessment = response.choices[0].message.content.strip()
        scores = parse_time_constrained_scores(assessment)

        result["time_limits"][label] = {
            "assessment": assessment,
            "scores": scores,
        }

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"  [qual] saved → {out_path}")
    return result



def cosine_similarity(v1: list, v2: list) -> float:
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = sum(a * a for a in v1) ** 0.5
    n2 = sum(b * b for b in v2) ** 0.5
    return dot / (n1 * n2) if n1 and n2 else 0.0


def get_embedding(client, text: str, model: str = "text-embedding-3-small") -> list:
    resp = client.embeddings.create(input=[text[:8000]], model=model)
    return resp.data[0].embedding


def run_sim_stage(scenario: dict, force: bool) -> dict | None:
    """Compute pairwise cosine similarity across all time limits + director."""
    from openai import OpenAI

    scenario_name = scenario["scenario_name"]
    out_dir = EVAL_TC_DIR / scenario_name
    out_path = out_dir / "cosine_similarity.json"

    if out_path.exists() and not force:
        print(f"  [sim] skip (exists): {scenario_name}")
        return json.loads(out_path.read_text())

    client = OpenAI()

    targets = dict(scenario["time_paths"])
    if scenario["director_path"]:
        targets["director"] = scenario["director_path"]

    print(f"  [sim] embedding {len(targets)} outputs for {scenario_name}…")
    embeddings = {}
    for label, path in targets.items():
        transcript = load_json(path)
        text = transcript_to_full_text(transcript)
        embeddings[label] = get_embedding(client, text)
        print(f"    embedded: {label}")

    labels = list(embeddings.keys())
    matrix = {}
    for la in labels:
        matrix[la] = {}
        for lb in labels:
            sim = cosine_similarity(embeddings[la], embeddings[lb])
            matrix[la][lb] = round(sim, 4)

    result = {
        "scenario": scenario_name,
        "labels": labels,
        "similarity_matrix": matrix,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"  [sim] saved → {out_path}")
    return result



def load_all_quant(scenario_names: list[str]) -> list[dict]:
    """Flatten quantitative results across scenarios into rows."""
    rows = []
    for sc_name in scenario_names:
        path = EVAL_TC_DIR / sc_name / "quantitative_metrics.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        for tl, metrics in data.get("time_limits", {}).items():
            row = {"scenario": sc_name, "time_limit": tl}
            row.update(metrics)
            rows.append(row)
    return rows


def load_all_qual(scenario_names: list[str]) -> list[dict]:
    """Flatten qualitative results across scenarios into rows."""
    rows = []
    for sc_name in scenario_names:
        path = EVAL_TC_DIR / sc_name / "qualitative_scores.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        for tl, entry in data.get("time_limits", {}).items():
            row = {"scenario": sc_name, "time_limit": tl}
            scores = entry.get("scores", {})
            row.update({k: v for k, v in scores.items()})
            rows.append(row)
    return rows


def load_all_sim(scenario_names: list[str]) -> list[dict]:
    """Flatten similarity results: for each scenario, row per (time_limit, director) pair."""
    rows = []
    for sc_name in scenario_names:
        path = EVAL_TC_DIR / sc_name / "cosine_similarity.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        matrix = data.get("similarity_matrix", {})
        for la, inner in matrix.items():
            for lb, sim in inner.items():
                if la >= lb:
                    continue  # deduplicate symmetric pairs
                rows.append({
                    "scenario": sc_name,
                    "label_a": la,
                    "label_b": lb,
                    "cosine_similarity": sim,
                })
    return rows


def save_table_csv_md(rows: list[dict], pivot_index: str, pivot_cols: str,
                       pivot_values: list[str], out_dir: Path, name: str):
    """Save a pivot table as CSV and Markdown without requiring pandas."""
    if not rows:
        print(f"  [tables] no data for {name}, skipping.")
        return

    # Build pivot: index × columns → value dict
    # For multiple values, take mean across scenarios
    from collections import defaultdict

    # Group by (index_val, col_val)
    groups: dict[tuple, list] = defaultdict(list)
    for row in rows:
        key = (row.get(pivot_index, ""), row.get(pivot_cols, ""))
        for v in pivot_values:
            if row.get(v) is not None:
                groups[(key[0], key[1], v)].append(row[v])

    # Unique index values and column values
    index_vals = sorted(set(r[pivot_index] for r in rows))
    col_vals_order = [tl for tl in (TIME_LIMITS + ["director"]) if any(r[pivot_cols] == tl for r in rows)]
    other_cols = sorted(set(r[pivot_cols] for r in rows) - set(col_vals_order))
    col_vals = col_vals_order + other_cols

    for value_col in pivot_values:
        header = [pivot_index] + col_vals
        file_safe_col = value_col.lower().replace(" ", "_").replace("/", "_")
        table_rows = []
        for idx_val in index_vals:
            row_data = [idx_val]
            for col_val in col_vals:
                vals = groups.get((idx_val, col_val, value_col), [])
                cell = round(mean(vals), 3) if vals else ""
                row_data.append(cell)
            table_rows.append(row_data)

        suffix = f"_{file_safe_col}" if len(pivot_values) > 1 else ""
        csv_path = out_dir / f"{name}{suffix}.csv"
        md_path = out_dir / f"{name}{suffix}.md"

        # CSV
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write(",".join(str(h) for h in header) + "\n")
            for r in table_rows:
                f.write(",".join(str(c) for c in r) + "\n")

        # Markdown
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("| " + " | ".join(str(h) for h in header) + " |\n")
            f.write("| " + " | ".join("---" for _ in header) + " |\n")
            for r in table_rows:
                f.write("| " + " | ".join(str(c) for c in r) + " |\n")

        print(f"  {name}{suffix}.{{csv,md}}")


def run_tables_stage(scenario_names: list[str]):
    """Generate summary tables from all saved results."""
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\nGenerating time-constrained summary tables → {SUMMARY_DIR}")

    # Quantitative: rows = scenario, cols = time_limit, values = each metric
    quant_rows = load_all_quant(scenario_names)
    if quant_rows:
        quant_metrics = [
            "scene_count", "beats_covered", "beat_cover_rate", "beat_completion_rate",
            "beat_merge_rate", "total_words", "words_per_beat",
            "pacing_variance", "truncated", "approx_tokens_per_second",
        ]
        for metric in quant_metrics:
            rows_with_val = [r for r in quant_rows if r.get(metric) is not None]
            if not rows_with_val:
                continue
            save_table_csv_md(
                rows=rows_with_val,
                pivot_index="scenario",
                pivot_cols="time_limit",
                pivot_values=[metric],
                out_dir=SUMMARY_DIR,
                name=f"time_constrained_{metric}",
            )

        # Also a combined quantitative overview table: index=time_limit, cols=metric, agg over scenarios
        from collections import defaultdict
        agg: dict[tuple, list] = defaultdict(list)
        for row in quant_rows:
            tl = row["time_limit"]
            for m in quant_metrics:
                v = row.get(m)
                if v is not None and v is not True and v is not False:
                    agg[(tl, m)].append(float(v))

        tl_vals = [tl for tl in (TIME_LIMITS + ["director"]) if any(k[0] == tl for k in agg)]
        header = ["time_limit"] + quant_metrics
        table_rows = []
        for tl in tl_vals:
            row_data = [tl]
            for m in quant_metrics:
                vals = agg.get((tl, m), [])
                row_data.append(round(mean(vals), 3) if vals else "")
            table_rows.append(row_data)

        for ext, open_fn in [("csv", lambda p: open(p, "w")), ("md", lambda p: open(p, "w"))]:
            path = SUMMARY_DIR / f"time_constrained_quantitative_overview.{ext}"
            with open_fn(path) as f:
                if ext == "csv":
                    f.write(",".join(str(h) for h in header) + "\n")
                    for r in table_rows:
                        f.write(",".join(str(c) for c in r) + "\n")
                else:
                    f.write("| " + " | ".join(str(h) for h in header) + " |\n")
                    f.write("| " + " | ".join("---" for _ in header) + " |\n")
                    for r in table_rows:
                        f.write("| " + " | ".join(str(c) for c in r) + " |\n")
        print(f"  time_constrained_quantitative_overview.{{csv,md}}")

    # Qualitative: index=time_limit, cols=dimension, mean over scenarios
    qual_rows = load_all_qual(scenario_names)
    if qual_rows:
        save_table_csv_md(
            rows=qual_rows,
            pivot_index="time_limit",
            pivot_cols="scenario",
            pivot_values=QUAL_DIMENSIONS,
            out_dir=SUMMARY_DIR,
            name="time_constrained_qualitative",
        )

        # Also: index=time_limit, cols=dimension, aggregated across scenarios
        from collections import defaultdict
        agg_q: dict[tuple, list] = defaultdict(list)
        for row in qual_rows:
            tl = row["time_limit"]
            for dim in QUAL_DIMENSIONS:
                v = row.get(dim)
                if v is not None:
                    agg_q[(tl, dim)].append(float(v))

        tl_vals_q = [tl for tl in (TIME_LIMITS + ["director"]) if any(k[0] == tl for k in agg_q)]
        header_q = ["time_limit"] + QUAL_DIMENSIONS
        table_rows_q = []
        for tl in tl_vals_q:
            row_data = [tl]
            for dim in QUAL_DIMENSIONS:
                vals = agg_q.get((tl, dim), [])
                row_data.append(round(mean(vals), 3) if vals else "")
            table_rows_q.append(row_data)

        for ext in ("csv", "md"):
            path = SUMMARY_DIR / f"time_constrained_qualitative_overview.{ext}"
            with open(path, "w") as f:
                if ext == "csv":
                    f.write(",".join(str(h) for h in header_q) + "\n")
                    for r in table_rows_q:
                        f.write(",".join(str(c) for c in r) + "\n")
                else:
                    f.write("| " + " | ".join(str(h) for h in header_q) + " |\n")
                    f.write("| " + " | ".join("---" for _ in header_q) + " |\n")
                    for r in table_rows_q:
                        f.write("| " + " | ".join(str(c) for c in r) + " |\n")
        print(f"  time_constrained_qualitative_overview.{{csv,md}}")

    # Similarity: pairs, mean cosine similarity across scenarios
    sim_rows = load_all_sim(scenario_names)
    if sim_rows:
        all_labels = sorted(set(r["label_a"] for r in sim_rows) | set(r["label_b"] for r in sim_rows))
        label_order = [tl for tl in (TIME_LIMITS + ["director"]) if tl in all_labels]
        other_labels = [l for l in all_labels if l not in label_order]
        ordered_labels = label_order + other_labels

        from collections import defaultdict
        pair_sims: dict[tuple, list] = defaultdict(list)
        for row in sim_rows:
            pair_sims[(row["label_a"], row["label_b"])].append(row["cosine_similarity"])
            pair_sims[(row["label_b"], row["label_a"])].append(row["cosine_similarity"])

        for ext in ("csv", "md"):
            path = SUMMARY_DIR / f"time_constrained_similarity.{ext}"
            with open(path, "w") as f:
                header_s = [""] + ordered_labels
                if ext == "csv":
                    f.write(",".join(header_s) + "\n")
                    for la in ordered_labels:
                        row_data = [la]
                        for lb in ordered_labels:
                            vals = pair_sims.get((la, lb), [])
                            row_data.append(round(mean(vals), 4) if vals else ("1.0" if la == lb else ""))
                        f.write(",".join(str(c) for c in row_data) + "\n")
                else:
                    f.write("| " + " | ".join(header_s) + " |\n")
                    f.write("| " + " | ".join("---" for _ in header_s) + " |\n")
                    for la in ordered_labels:
                        row_data = [la]
                        for lb in ordered_labels:
                            vals = pair_sims.get((la, lb), [])
                            row_data.append(round(mean(vals), 4) if vals else ("1.0" if la == lb else ""))
                        f.write("| " + " | ".join(str(c) for c in row_data) + " |\n")
        print(f"  time_constrained_similarity.{{csv,md}}")



def main():
    parser = argparse.ArgumentParser(
        description="Evaluate time-constrained director-agent outputs."
    )
    parser.add_argument("--dry-run", action="store_true", help="Show plan without running.")
    parser.add_argument(
        "--only",
        choices=["quant", "qual", "sim", "tables"],
        default=None,
        help="Run only one stage. Default: run all stages.",
    )
    parser.add_argument("--scenario", default=None, help="Evaluate only this scenario.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Evaluator model for qual stage.")
    parser.add_argument("--force", action="store_true", help="Re-run stages even if results exist.")
    args = parser.parse_args()

    run_quant = args.only in (None, "quant")
    run_qual = args.only in (None, "qual")
    run_sim = args.only in (None, "sim")
    run_tables = args.only in (None, "tables")

    scenarios = discover_scenarios(args.scenario)
    scenario_names = [s["scenario_name"] for s in scenarios]

    print(f"Time-constrained scenarios found: {len(scenarios)}")
    for sc in scenarios:
        tls = list(sc["time_paths"].keys())
        director_status = "director ✓" if sc["director_path"] else "no director"
        print(f"  {sc['scenario_name']}: {tls} | {director_status}")

    if args.dry_run:
        print("\n-- dry run, stopping here --")
        return

    if not scenarios:
        print("Nothing to evaluate.")
        return

    if run_quant:
        print(f"\n{'='*60}\nQUANTITATIVE STAGE\n{'='*60}")
        for sc in scenarios:
            try:
                run_quant_stage(sc, force=args.force)
            except Exception as e:
                print(f"  ERROR [{sc['scenario_name']}]: {e}")

    if run_qual:
        print(f"\n{'='*60}\nQUALITATIVE STAGE (model: {args.model})\n{'='*60}")
        for sc in scenarios:
            try:
                run_qual_stage(sc, model=args.model, force=args.force)
            except Exception as e:
                print(f"  ERROR [{sc['scenario_name']}]: {e}")

    if run_sim:
        print(f"\n{'='*60}\nSIMILARITY STAGE\n{'='*60}")
        for sc in scenarios:
            try:
                run_sim_stage(sc, force=args.force)
            except Exception as e:
                print(f"  ERROR [{sc['scenario_name']}]: {e}")

    if run_tables:
        print(f"\n{'='*60}\nTABLES STAGE\n{'='*60}")
        # Use all discovered scenarios (not just the filtered subset) for tables
        all_tc_names = [d.name for d in EVAL_TC_DIR.iterdir() if d.is_dir()] if EVAL_TC_DIR.exists() else scenario_names
        run_tables_stage(all_tc_names)

    print(f"\nDone.")


if __name__ == "__main__":
    main()
