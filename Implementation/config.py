"""Model names used across the project; values are the ones used for the thesis results."""

# --- Scripted (batch) story generation ---
# Baseline storyteller: baseline/, experiments/run_baseline_*
BASELINE_MODEL = "gpt-4o-mini"
# Director + actor: director_agent/auto_main*.py, time_constrained/time_auto_main.py
DIRECTOR_BATCH_MODEL = "gpt-5.5"

# --- Interactive terminal and realtime voice apps ---
# Director + actor: director_agent/main.py, time_main.py, time_strict_auto_main.py
INTERACTIVE_MODEL = "gpt-4o-mini"
# Director LLM behind the realtime voice apps
REALTIME_DIRECTOR_MODEL = "gpt-4o-mini"
# OpenAI Realtime voice model
REALTIME_MODEL = "gpt-realtime"

# --- Evaluation ---
# LLM-as-judge default for all batch evaluation scripts
JUDGE_MODEL = "gpt-4o"
# Default --model of evaluation_agent/evaluation_core.py only
EVALUATION_CORE_CLI_MODEL = "gpt-5.5"
# Director/character model passed to the CoDi baseline
CODI_MODEL = "gpt-4o"
# Embeddings for the cosine-similarity stage of evaluate_time_constrained.py
EMBEDDING_MODEL = "text-embedding-3-small"
