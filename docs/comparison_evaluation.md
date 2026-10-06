# CoDi vs. Implementation - Thesis Evaluation Framework

This framework provides specialized tools for robust, thesis-level comparative evaluation between your **Implementation Director Agent** and the **CoDi Framework**.

## Overview

The evaluation system is designed specifically to:
- Compare storytelling quality across multiple dimensions
- Generate quantifiable metrics for thesis validation
- Identify system strengths and use-case suitability
- Provide statistical aggregation across multiple runs
- Generate publication-ready reports

## Components

### 1. **Comparison Evaluator** (`evaluation_agent/comparison_evaluator.py`)
Specialized pairwise evaluator comparing CoDi and Implementation outputs on the same scenario.

**Features:**
- Converts CoDi JSON outputs to your transcript format automatically
- Runs detailed comparative analysis on 8 dimensions
- Evaluates individual system effectiveness
- Generates comparison-specific insights

**Dimensions evaluated:**
- Plot & Structure
- Narrative Control & Progression
- Character Consistency & Fidelity
- Language & Expressiveness
- Interactive Response & Interruption Handling
- Creative Elements
- Detail & Thoroughness (✓ CoDi advantage)
- Narrative Polish & Refinement (✓ CoDi advantage)
- System-Specific Strengths

### 2. **Comparison Prompts** (`evaluation_agent/comparison_prompts.py`)
Extended evaluation prompts specifically designed for thesis evaluation.

**Includes:**
- `COMPARE_SYSTEMS_AB_PROMPT`: Detailed comparative framework
- `SYSTEM_EFFECTIVENESS_PROMPT`: Individual system analysis
- `AGGREGATE_COMPARISON_SUMMARY_PROMPT`: LLM-powered thesis summary
- `DIMENSION_SCORER_PROMPT`: Granular dimension scoring
- Complete dimension rubrics (1-10 scale scoring guidelines)

### 3. **Analysis & Aggregation** (`comparison_analysis.py`)
Statistical pipeline for aggregating results across multiple comparison runs.

**Generates:**
- Comparative statistics (win rates, confidence)
- Scenario-specific performance breakdown
- Story metrics analysis (length, turns, efficiency)
- Scenario strengths report (which system excels where)
- LLM-powered thesis summary
- Publication-ready markdown report

## Quick Start

### Step 1: Generate Stories

First, generate stories from both systems on the same scenario:

```bash
# Generate from Implementation
cd Implementation
python director_agent/main.py --character olaf --scenario olaf_retells_red_riding_hood

# Generate from CoDi
cd ../CoDi-main/CoDi-main
source venv/bin/activate
./scripts/generate.sh  # Output to outputs/generation/
```

### Step 2: Run Single Comparison

Compare one pair of outputs:

```bash
cd Disney/Implementation

python -m evaluation_agent.comparison_evaluator \
    --implementation-file Implementation/director_agent/outputs/your_run.json \
    --codi-file CoDi-main/CoDi-main/outputs/generation/your_codi_output.json \
    --character character_prompts.olaf \
    --scenario olaf_retells_red_riding_hood \
    --model gpt-4o \
    --out-dir Implementation/comparison_results/olaf_retells_red_riding_hood
```

### Step 3: Run Multiple Comparisons (Batch)

For thesis robustness, run multiple comparisons across different scenarios:

```bash
# Run comparisons for each scenario pair
for scenario in "olaf_retells_red_riding_hood" "olaf_first_summer_picnic" "olaf_lost_snowflake"; do
    python -m evaluation_agent.comparison_evaluator \
        --implementation-file Implementation/outputs/$scenario/run_1.json \
        --codi-file CoDi-main/CoDi-main/outputs/generation/codi_$scenario.json \
        --character character_prompts.olaf \
        --scenario $scenario \
        --model gpt-4o
done
```

### Step 4: Aggregate and Analyze

Analyze all comparison results and generate thesis reports:

```bash
python comparison_analysis.py \
    --results-dir Implementation/comparison_results \
    --out-dir Implementation/comparison_analysis \
    --model gpt-4o
```

This generates:
- `thesis_evaluation_report.md` - Publication-ready report
- `detailed_analysis.json` - Machine-readable results

## Output Structure

### Comparison Result Structure
```json
{
  "timestamp": "2026-06-02T10:30:00",
  "scenario": "olaf_retells_red_riding_hood",
  "comparison_evaluation": {
    "comparative_scores": {
      "plot_structure": "A",
      "narrative_control": "A",
      "character_fidelity": "A",
      ...
    },
    "assessment": "detailed text analysis",
    "implementation_story_length": 5234,
    "codi_story_length": 4892
  },
  "implementation_effectiveness": {...},
  "codi_effectiveness": {...}
}
```

### Analysis Report Structure
```json
{
  "analysis": {
    "overall_statistics": {
      "plot_structure": {
        "implementation_wins": 8,
        "codi_wins": 2,
        "implementation_win_rate": 80.0,
        ...
      }
    },
    "story_metrics": {
      "implementation": {
        "story_length_stats": {...},
        "turn_count_stats": {...}
      }
    }
  },
  "scenario_strengths": {
    "scenario_name": {
      "overall_winner": "Implementation",
      "implementation_wins": 24,
      "codi_wins": 12
    }
  }
}
```

## Key Evaluation Dimensions

### Plot & Structure
- Clear beginning, middle, end
- Logical event progression
- Beat structure adherence
- Coherence and consistency

### Narrative Control
- Smooth beat transitions
- Avoidance of repetition/loops
- Timely progression
- Compelling momentum

### Character Fidelity
- Profile alignment
- Authentic voice
- Consistent personality
- No generic assistant behavior

### Language & Expressiveness
- Vocabulary variety
- Sentence structure variation
- Appropriate tone
- Use of literary devices

### Interactive Response
- Interruption handling (unique to Implementation)
- Natural acknowledgment of input
- Seamless story re-integration
- User agency respect

### Creative Elements
- Original story additions
- Intentional creativity
- Story coherence maintenance
- Engagement enhancement

### Detail & Thoroughness (CoDi Advantage)
- Rich narrative development
- Detailed setting descriptions
- Complete scene fleshing-out
- Comprehensive world-building
- Scene-setting depth

### Narrative Polish & Refinement (CoDi Advantage)
- Prose quality and editing
- Grammar and flow
- Smooth transitions
- Writing refinement
- Editorial quality

## Thesis-Specific Insights

The framework is designed to answer key thesis questions:

1. **Which system produces higher quality narratives?**
   - Answered through comparative scores across dimensions

2. **When is each system better suited?**
   - Answered through scenario-specific breakdown
   - Shows strengths/weaknesses in different contexts

3. **How quantifiable is the difference?**
   - Win rate statistics and percentages
   - Story metrics comparison
   - Dimension-level breakdown

4. **What are the trade-offs?**
   - System-specific strengths analysis
   - Identifies unique advantages of each approach
   - Highlights design choice impacts

5. **Is interruption handling a competitive advantage?**
   - Direct evaluation on your unique dimension
   - Shows Implementation's interactive strengths
   - Quantifies impact on narrative flow

## Advanced Usage

### Scoring Individual Dimensions

For granular analysis, score specific dimensions separately:

```python
from evaluation_agent.comparison_prompts import DIMENSION_SCORER_PROMPT, DIMENSION_RUBRICS
from evaluation_agent.comparison_evaluator import call_evaluator

# Score interruption handling
prompt = DIMENSION_SCORER_PROMPT.format(
    dimension="Interruption Handling",
    dimension_description="How gracefully does the system handle user interruptions?",
    rubric=DIMENSION_RUBRICS["interactive_response"],
    story=your_story,
    character_profile=profile,
    scenario="olaf_retells_red_riding_hood",
    system="Implementation"
)

score = call_evaluator(client, model, prompt)
```

### Custom Batch Evaluation

Create your own batch evaluation script using the components:

```python
from evaluation_agent.comparison_evaluator import (
    make_client,
    load_json,
    convert_codi_output_to_transcript,
    run_comparison_evaluation,
)

client = make_client()

# Load and evaluate multiple scenario pairs
for scenario in scenarios:
    impl_transcript = load_json(f"outputs/{scenario}/impl.json")["transcript"]
    codi_transcript = convert_codi_output_to_transcript(f"outputs/{scenario}/codi.json")
    
    result = run_comparison_evaluation(
        impl_transcript,
        codi_transcript,
        character_profile,
        character_name,
        scenario,
        client,
        "gpt-4o"
    )
    # Process result...
```

## Configuration

### Environment Variables
Ensure `.env` file exists in Implementation directory:
```env
OPENAI_API_KEY=your_api_key
```

### Model Selection
- `gpt-4o` (default): Best quality for thesis evaluation
- `gpt-4-turbo`: Good balance of quality and cost
- Other compatible OpenAI models supported

### Output Directories
- Comparison results: `Implementation/comparison_results/{scenario}/`
- Analysis reports: `Implementation/comparison_analysis/`
- Detailed JSON: `Implementation/comparison_analysis/detailed_analysis.json`

## Best Practices for Thesis Evaluation

1. **Multiple Runs per Scenario**
   - Run 3-5 comparisons per scenario for statistical validity
   - Variation shows system reliability

2. **Diverse Scenarios**
   - Test with/without interruptions
   - Test different complexity levels
   - Test different characters

3. **Systematic Documentation**
   - Store all comparison results
   - Keep generated stories for reference
   - Document any system changes between runs

4. **Iterative Analysis**
   - Start with aggregate analysis
   - Drill down into specific scenarios
   - Review qualitative assessments alongside metrics

5. **Reproducibility**
   - Record models used for evaluation
   - Save all prompts and parameters
   - Version control your evaluation framework

## Interpreting Results

### Win Rate Interpretation
- **80%+ win rate**: Clear advantage in dimension
- **60-80% win rate**: Moderate advantage
- **40-60% win rate**: Comparable performance
- **<40% win rate**: Disadvantage in dimension

### Story Metrics Interpretation
- **Story Length**: Longer isn't always better; reflects detail level
- **Turn Count**: Higher turns may indicate pacing issues or engagement
- **Completion Rate**: Percentage of runs that reach resolution

### Scenario Patterns
- If Implementation wins more in interrupted scenarios, interruption handling is valuable
- If CoDi wins more in complex scenarios, multi-agent approach benefits complexity
- Consistent winners suggest fundamental approach advantages

## Troubleshooting

### CoDi Output Conversion Issues
If conversion fails, check:
- CoDi output JSON structure matches expected format
- Narrative key exists in output
- Turn structure uses standard naming (turn_N format)

### Evaluation Timeout
- Decrease story length being evaluated
- Try shorter scenario with fewer turns
- Split evaluations across multiple smaller batches

### Memory Issues
- Process scenarios one at a time
- Reduce number of concurrent comparisons
- Archive older comparison results

## References

- Implementation framework: See `Implementation/ReadMe.md`
- CoDi framework: See `CoDi-main/README.md`
- Original evaluation framework: `Implementation/evaluation_agent/README.md`

## Citation

When using this framework in your thesis, reference:

```bibtex
@misc{implementation_codi_evaluation,
  title={Comparative Evaluation Framework for Interactive Story Generation Systems},
  author={Your Name},
  year={2026}
}
```

## Support

For issues or questions:
1. Check this README and component docstrings
2. Review comparison result JSON for detailed assessments
3. Examine individual comparison_*.json files for specific evaluations
