#!/bin/bash

# evaluation/run_eval.sh
#
# Run from the Implementation folder:
#
#   bash evaluation/run_eval.sh
#
# This compares:
# - baseline output
# - director-agent output

python evaluation_agent/evaluation_core.py \
  --story-a baseline/outputs/baseline_transcript_olaf.json \
  --story-b director_agent/outputs/director_agent_transcript_olaf.json \
  --character-module character_prompts.olaf \
  --out-dir evaluation_results \
  --model gpt-5.5 \
  --ab-ba