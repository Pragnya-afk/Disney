#!/bin/bash

cd "$(dirname "$0")/.."

source venv/bin/activate
source scripts/env.sh

python generation.py \
  --data-file "$DATA_FILE_PATH" \
  --out-dir ./outputs/generation \
  --plan-mode \
  --max-turn 30 \
  --planner-agent-base-model gpt-4o \
  --director-agent-base-model gpt-4o \
  --character-agent-base-model gpt-4o \
  --editor-agent-base-model gpt-4o