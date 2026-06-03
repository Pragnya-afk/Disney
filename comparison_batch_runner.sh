#!/bin/bash
# comparison_batch_runner.sh
#
# Quick batch script to run multiple comparisons for thesis evaluation.
# This script helps generate comparable results across multiple scenarios.
#
# Usage:
#   ./comparison_batch_runner.sh --impl-dir Implementation/outputs --codi-dir CoDi-main/CoDi-main/outputs/generation --scenarios "scenario1,scenario2"
#
# Or copy one of the example usages below and run directly.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMPL_DIR=""
CODI_DIR=""
SCENARIOS=""
CHARACTER="character_prompts.olaf"
MODEL="gpt-4o"
OUT_BASE="Implementation/comparison_results"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --impl-dir)
            IMPL_DIR="$2"
            shift 2
            ;;
        --codi-dir)
            CODI_DIR="$2"
            shift 2
            ;;
        --scenarios)
            SCENARIOS="$2"
            shift 2
            ;;
        --character)
            CHARACTER="$2"
            shift 2
            ;;
        --model)
            MODEL="$2"
            shift 2
            ;;
        --out-base)
            OUT_BASE="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Validate inputs
if [ -z "$IMPL_DIR" ] || [ -z "$CODI_DIR" ] || [ -z "$SCENARIOS" ]; then
    echo "Usage: $0 --impl-dir <dir> --codi-dir <dir> --scenarios <scenario_list>"
    echo ""
    echo "Example 1 - Single scenario:"
    echo "  $0 --impl-dir Implementation/outputs --codi-dir CoDi-main/outputs/generation --scenarios olaf_retells_red_riding_hood"
    echo ""
    echo "Example 2 - Multiple scenarios:"
    echo "  $0 --impl-dir Implementation/outputs --codi-dir CoDi-main/outputs/generation --scenarios \"olaf_retells_red_riding_hood,olaf_first_summer_picnic\""
    echo ""
    exit 1
fi

# Convert comma-separated scenarios to array
IFS=',' read -ra SCENARIO_ARRAY <<< "$SCENARIOS"

echo "=========================================="
echo "CoDi vs Implementation - Batch Evaluation"
echo "=========================================="
echo "Implementation Dir: $IMPL_DIR"
echo "CoDi Dir: $CODI_DIR"
echo "Character: $CHARACTER"
echo "Evaluator Model: $MODEL"
echo "Scenarios: ${SCENARIO_ARRAY[@]}"
echo ""

TOTAL_SCENARIOS=${#SCENARIO_ARRAY[@]}
CURRENT=0

for scenario in "${SCENARIO_ARRAY[@]}"; do
    CURRENT=$((CURRENT + 1))
    echo "[$CURRENT/$TOTAL_SCENARIOS] Evaluating scenario: $scenario"
    
    # Find implementation output
    IMPL_FILE=$(find "$IMPL_DIR" -name "*${scenario}*" -type f | head -1)
    if [ -z "$IMPL_FILE" ]; then
        echo "  WARNING: Implementation file not found for scenario $scenario"
        continue
    fi
    
    # Find CoDi output
    CODI_FILE=$(find "$CODI_DIR" -name "*${scenario}*" -type f | head -1)
    if [ -z "$CODI_FILE" ]; then
        echo "  WARNING: CoDi file not found for scenario $scenario"
        continue
    fi
    
    echo "  Implementation: $IMPL_FILE"
    echo "  CoDi: $CODI_FILE"
    
    # Run comparison
    cd "$SCRIPT_DIR"
    python -m evaluation_agent.comparison_evaluator \
        --implementation-file "$IMPL_FILE" \
        --codi-file "$CODI_FILE" \
        --character "$CHARACTER" \
        --scenario "$scenario" \
        --model "$MODEL" \
        --out-dir "$OUT_BASE/$scenario" 2>&1 | sed 's/^/  /'
    
    echo ""
done

echo "=========================================="
echo "Batch evaluation complete!"
echo "Results saved to: $OUT_BASE/"
echo ""
echo "Next step - Aggregate results:"
echo "  python comparison_analysis.py --results-dir $OUT_BASE"
echo "=========================================="
