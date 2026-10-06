"""Model names used across the project; values are the ones used for the thesis results."""

# Scripted (batch) story generation
BASELINE_MODEL = "gpt-4o-mini"  # baseline storyteller (baseline/, experiments/run_baseline_*)
DIRECTOR_BATCH_MODEL = "gpt-5.5"  # director + actor in director_agent/auto_main*.py and time_auto_main.py

# Interactive terminal and realtime voice apps
INTERACTIVE_MODEL = "gpt-4o-mini"  # director + actor in director_agent/main.py, time_main.py, time_strict_auto_main.py
REALTIME_DIRECTOR_MODEL = "gpt-4o-mini"  # director LLM behind the realtime voice apps
REALTIME_MODEL = "gpt-realtime"  # OpenAI Realtime voice model

# Evaluation
JUDGE_MODEL = "gpt-4o"  # LLM-as-judge default for all batch evaluation scripts
EVALUATION_CORE_CLI_MODEL = "gpt-5.5"  # default --model of evaluation_agent/evaluation_core.py only
CODI_MODEL = "gpt-4o"  # director/character model passed to the CoDi baseline
EMBEDDING_MODEL = "text-embedding-3-small"  # cosine-similarity stage of evaluate_time_constrained.py
