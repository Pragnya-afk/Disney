"""
comparison_analysis.py

Aggregation and statistical analysis pipeline for thesis evaluation.
Summarizes multiple comparison runs and generates insights for publication.

Usage:
    python comparison_analysis.py \
        --results-dir implementation/comparison_results \
        --out-dir implementation/comparison_analysis \
        --model gpt-4o
"""

import os
import sys
import json
import argparse
import importlib
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from statistics import mean, stdev
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv
from openai import OpenAI

CURRENT_DIR = os.path.dirname(__file__)
IMPLEMENTATION_DIR = CURRENT_DIR
sys.path.append(IMPLEMENTATION_DIR)

from evaluation_agent.comparison_prompts import AGGREGATE_COMPARISON_SUMMARY_PROMPT
from evaluation_agent.evaluation_core import make_client

# Load environment
load_dotenv(os.path.join(IMPLEMENTATION_DIR, ".env"))


# ============================================================================
# Data loading and aggregation
# ============================================================================

def load_json(path: str) -> Dict[str, Any]:
    """Load JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_all_comparison_results(results_dir: str) -> Dict[str, List[Dict]]:
    """
    Find all comparison results organized by scenario.
    Returns {scenario_name: [result_files]}
    """
    results_by_scenario = defaultdict(list)
    
    results_path = Path(results_dir)
    if not results_path.exists():
        print(f"Results directory not found: {results_dir}")
        return results_by_scenario
    
    for result_file in results_path.glob("**/comparison_*.json"):
        data = load_json(str(result_file))
        scenario = data.get("scenario", "unknown")
        results_by_scenario[scenario].append({
            "file": str(result_file),
            "data": data,
        })
    
    return results_by_scenario


# ============================================================================
# Statistical analysis
# ============================================================================

def analyze_comparative_scores(results_by_scenario: Dict) -> Dict[str, Any]:
    """
    Analyze comparative scores across all scenarios.
    Returns aggregated statistics and winner frequencies.
    """
    
    all_dimensions = set()
    dimension_winners = defaultdict(lambda: {"A": 0, "B": 0, "Comparable": 0})
    scenario_stats = {}
    
    # Collect all results
    for scenario, results_list in results_by_scenario.items():
        scenario_scores = defaultdict(lambda: {"A": 0, "B": 0, "Comparable": 0})
        
        for result_item in results_list:
            scores = result_item["data"].get("comparison_evaluation", {}).get("comparative_scores", {})
            for dimension, winner in scores.items():
                all_dimensions.add(dimension)
                scenario_scores[dimension][winner] += 1
                dimension_winners[dimension][winner] += 1
        
        # Calculate scenario-level winner for each dimension
        scenario_summary = {}
        for dimension, counts in scenario_scores.items():
            total = sum(counts.values())
            if total > 0:
                max_winner = max(counts.items(), key=lambda x: x[1])[0]
                scenario_summary[dimension] = {
                    "winner": max_winner,
                    "counts": counts,
                    "total_runs": total,
                }
        
        scenario_stats[scenario] = scenario_summary
    
    # Calculate overall statistics
    overall_stats = {}
    for dimension in all_dimensions:
        counts = dimension_winners[dimension]
        total = sum(counts.values())
        win_rate_a = (counts["A"] / total * 100) if total > 0 else 0
        win_rate_b = (counts["B"] / total * 100) if total > 0 else 0
        
        overall_stats[dimension] = {
            "implementation_wins": counts["A"],
            "codi_wins": counts["B"],
            "comparable": counts["Comparable"],
            "total_evaluations": total,
            "implementation_win_rate": round(win_rate_a, 1),
            "codi_win_rate": round(win_rate_b, 1),
        }
    
    return {
        "overall_statistics": overall_stats,
        "scenario_statistics": scenario_stats,
        "dimensions_evaluated": list(all_dimensions),
    }


def extract_story_metrics(results_by_scenario: Dict) -> Dict[str, Any]:
    """
    Extract story generation metrics (length, turns, etc.)
    """
    
    metrics = {
        "implementation": {
            "story_lengths": [],
            "turn_counts": [],
            "runs": 0,
        },
        "codi": {
            "story_lengths": [],
            "turn_counts": [],
            "runs": 0,
        },
    }
    
    for scenario, results_list in results_by_scenario.items():
        for result_item in results_list:
            comp_eval = result_item["data"].get("comparison_evaluation", {})
            
            impl_len = comp_eval.get("implementation_story_length", 0)
            impl_turns = comp_eval.get("implementation_turns", 0)
            codi_len = comp_eval.get("codi_story_length", 0)
            codi_turns = comp_eval.get("codi_turns", 0)
            
            if impl_len > 0:
                metrics["implementation"]["story_lengths"].append(impl_len)
                metrics["implementation"]["turn_counts"].append(impl_turns)
                metrics["implementation"]["runs"] += 1
            
            if codi_len > 0:
                metrics["codi"]["story_lengths"].append(codi_len)
                metrics["codi"]["turn_counts"].append(codi_turns)
                metrics["codi"]["runs"] += 1
    
    # Calculate statistics
    def calc_stats(values: List[float]) -> Dict:
        if not values:
            return {}
        return {
            "mean": round(mean(values), 1),
            "min": min(values),
            "max": max(values),
            "stdev": round(stdev(values), 1) if len(values) > 1 else 0,
        }
    
    return {
        "implementation": {
            "runs": metrics["implementation"]["runs"],
            "story_length_stats": calc_stats(metrics["implementation"]["story_lengths"]),
            "turn_count_stats": calc_stats(metrics["implementation"]["turn_counts"]),
        },
        "codi": {
            "runs": metrics["codi"]["runs"],
            "story_length_stats": calc_stats(metrics["codi"]["story_lengths"]),
            "turn_count_stats": calc_stats(metrics["codi"]["turn_counts"]),
        },
    }


def build_scenario_strengths_report(results_by_scenario: Dict) -> Dict[str, Any]:
    """
    Identify which system performs better in which scenarios.
    """
    
    scenario_report = {}
    
    for scenario, results_list in results_by_scenario.items():
        dimension_wins = defaultdict(lambda: {"A": 0, "B": 0, "Comparable": 0})
        
        for result_item in results_list:
            scores = result_item["data"].get("comparison_evaluation", {}).get("comparative_scores", {})
            for dimension, winner in scores.items():
                dimension_wins[dimension][winner] += 1
        
        # Determine overall winner for scenario
        total_a = sum(counts["A"] for counts in dimension_wins.values())
        total_b = sum(counts["B"] for counts in dimension_wins.values())
        
        if total_a > total_b:
            scenario_winner = "Implementation"
        elif total_b > total_a:
            scenario_winner = "CoDi"
        else:
            scenario_winner = "Comparable"
        
        scenario_report[scenario] = {
            "overall_winner": scenario_winner,
            "implementation_wins": total_a,
            "codi_wins": total_b,
            "dimension_breakdown": dict(dimension_wins),
            "runs": len(results_list),
        }
    
    return scenario_report


# ============================================================================
# Report generation
# ============================================================================

def generate_thesis_summary_report(
    analysis_data: Dict[str, Any],
    results_by_scenario: Dict,
    client: OpenAI,
    model: str,
) -> str:
    """
    Generate comprehensive thesis summary using LLM.
    """
    
    # Format data for LLM
    evaluation_data_str = json.dumps({
        "overall_statistics": analysis_data["overall_statistics"],
        "scenario_statistics": analysis_data["scenario_statistics"],
        "story_metrics": analysis_data["story_metrics"],
    }, indent=2)
    
    prompt = AGGREGATE_COMPARISON_SUMMARY_PROMPT.format(
        evaluation_data=evaluation_data_str,
    )
    
    response = client.chat.completions.create(
        model=model,
        temperature=0.3,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert in interactive storytelling evaluation. "
                    "Generate comprehensive thesis-level insights from the provided evaluation data."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
    )
    
    return response.choices[0].message.content.strip()


def create_markdown_report(
    analysis_data: Dict[str, Any],
    scenario_strengths: Dict[str, Any],
    story_metrics: Dict[str, Any],
    thesis_summary: str,
    output_file: str,
) -> None:
    """
    Create formatted markdown report suitable for thesis.
    """
    
    content = []
    content.append("# CoDi vs. Implementation Director Agent - Comparative Evaluation Report\n")
    content.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n\n")
    
    # Executive Summary
    content.append("## Executive Summary\n")
    content.append(thesis_summary)
    content.append("\n\n")
    
    # Overall Statistics
    content.append("## Overall Comparative Statistics\n\n")
    overall_stats = analysis_data["overall_statistics"]
    
    content.append("| Dimension | Implementation Wins | CoDi Wins | Comparable | Implementation Win Rate |\n")
    content.append("|-----------|-------------------|----------|-----------|------------------------|\n")
    
    for dimension, stats in sorted(overall_stats.items()):
        impl_wins = stats["implementation_wins"]
        codi_wins = stats["codi_wins"]
        comparable = stats["comparable"]
        impl_rate = stats["implementation_win_rate"]
        
        content.append(
            f"| {dimension.replace('_', ' ').title()} | {impl_wins} | {codi_wins} | "
            f"{comparable} | {impl_rate}% |\n"
        )
    
    content.append("\n")
    
    # Scenario Breakdown
    content.append("## Performance by Scenario\n\n")
    
    for scenario, report in sorted(scenario_strengths.items()):
        winner = report["overall_winner"]
        impl_wins = report["implementation_wins"]
        codi_wins = report["codi_wins"]
        runs = report["runs"]
        
        content.append(f"### {scenario}\n")
        content.append(f"- **Overall Winner**: {winner}\n")
        content.append(f"- **Runs**: {runs}\n")
        content.append(f"- **Implementation Wins**: {impl_wins}\n")
        content.append(f"- **CoDi Wins**: {codi_wins}\n")
        content.append("\n")
    
    # Story Metrics
    content.append("## Story Generation Metrics\n\n")
    
    impl_metrics = story_metrics["implementation"]
    codi_metrics = story_metrics["codi"]
    
    content.append(f"### Implementation Director Agent\n")
    content.append(f"- **Total Runs**: {impl_metrics['runs']}\n")
    
    if impl_metrics['story_length_stats']:
        content.append(f"- **Story Length (characters)**:\n")
        for key, val in impl_metrics['story_length_stats'].items():
            content.append(f"  - {key.capitalize()}: {val}\n")
    
    if impl_metrics['turn_count_stats']:
        content.append(f"- **Turn Count**:\n")
        for key, val in impl_metrics['turn_count_stats'].items():
            content.append(f"  - {key.capitalize()}: {val}\n")
    
    content.append(f"\n### CoDi Framework\n")
    content.append(f"- **Total Runs**: {codi_metrics['runs']}\n")
    
    if codi_metrics['story_length_stats']:
        content.append(f"- **Story Length (characters)**:\n")
        for key, val in codi_metrics['story_length_stats'].items():
            content.append(f"  - {key.capitalize()}: {val}\n")
    
    if codi_metrics['turn_count_stats']:
        content.append(f"- **Turn Count**:\n")
        for key, val in codi_metrics['turn_count_stats'].items():
            content.append(f"  - {key.capitalize()}: {val}\n")
    
    content.append("\n")
    
    # Write report
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("".join(content))


# ============================================================================
# Main analysis orchestration
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Aggregate and analyze thesis-level comparison results"
    )
    
    parser.add_argument(
        "--results-dir",
        default="implementation/comparison_results",
        help="Directory containing comparison results",
    )
    parser.add_argument(
        "--out-dir",
        default="implementation/comparison_analysis",
        help="Output directory for analysis reports",
    )
    parser.add_argument(
        "--model",
        default="gpt-4o",
        help="Model to use for LLM-based summarization",
    )
    
    args = parser.parse_args()
    
    # Ensure output directory exists
    os.makedirs(args.out_dir, exist_ok=True)
    
    print(f"Loading comparison results from {args.results_dir}...")
    results_by_scenario = find_all_comparison_results(args.results_dir)
    
    if not results_by_scenario:
        print(f"No comparison results found in {args.results_dir}")
        return
    
    print(f"Found results for {len(results_by_scenario)} scenarios")
    
    # Run analysis
    print("Running statistical analysis...")
    comparative_analysis = analyze_comparative_scores(results_by_scenario)
    story_metrics = extract_story_metrics(results_by_scenario)
    scenario_strengths = build_scenario_strengths_report(results_by_scenario)
    
    # Prepare full analysis data
    analysis_data = {
        **comparative_analysis,
        "story_metrics": story_metrics,
    }
    
    # Generate LLM-based summary
    print(f"Generating thesis summary using {args.model}...")
    client = make_client()
    thesis_summary = generate_thesis_summary_report(
        analysis_data,
        results_by_scenario,
        client,
        args.model,
    )
    
    # Create markdown report
    report_file = os.path.join(args.out_dir, "thesis_evaluation_report.md")
    print(f"Creating markdown report at {report_file}...")
    create_markdown_report(
        analysis_data,
        scenario_strengths,
        story_metrics,
        thesis_summary,
        report_file,
    )
    
    # Save detailed JSON analysis
    json_file = os.path.join(args.out_dir, "detailed_analysis.json")
    print(f"Saving detailed analysis to {json_file}...")
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "analysis": analysis_data,
            "scenario_strengths": scenario_strengths,
            "thesis_summary": thesis_summary,
        }, f, indent=2, ensure_ascii=False)
    
    # Print summary to console
    print("\n" + "="*70)
    print("ANALYSIS SUMMARY")
    print("="*70)
    print(f"\nScenarios analyzed: {len(results_by_scenario)}")
    
    overall = analysis_data["overall_statistics"]
    total_evals = sum(s["total_evaluations"] for s in overall.values()) // len(overall)
    
    impl_total_wins = sum(s["implementation_wins"] for s in overall.values())
    codi_total_wins = sum(s["codi_wins"] for s in overall.values())
    
    print(f"Total evaluations per dimension: {total_evals}")
    print(f"\nImplementation total wins: {impl_total_wins}")
    print(f"CoDi total wins: {codi_total_wins}")
    print(f"\nReports generated:")
    print(f"  - Markdown report: {report_file}")
    print(f"  - Detailed JSON: {json_file}")
    print("="*70)


if __name__ == "__main__":
    main()
