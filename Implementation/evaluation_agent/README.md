Evaluation scripts and helpers

Purpose:
- This folder contains scripts used to run evaluations on story transcripts.
-- Typical flow: generate transcripts -> run `evaluation_agent/run_batch_eval.py` or `evaluation_agent/evaluation_core.py` -> write outputs to `Implementation/evaluation_results/`.

Conventions:
-- Code lives in `Implementation/evaluation_agent/`.
- Evaluation outputs/results live in `Implementation/evaluation_results/`.
- Use `--out-dir` to override the default output directory (defaults to `Implementation/evaluation_results/`).
