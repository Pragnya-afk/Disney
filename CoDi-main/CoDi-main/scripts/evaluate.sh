#!/bin/bash
source scripts/env.sh

python score_evaluation.py \
  --out-dir $EVAL_DIR \
  --out-dir-stat $STAT_DIR \
  --evaluate-story-quality-ab \
  --data-file ./outputs/generation/olaf_anna_01_noplan.json \
  --data-file-b ./outputs/generation/olaf_anna_01_plan.json \
  --evaluator-agent-base-model gpt-4o