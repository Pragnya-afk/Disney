"""Model names used by the live apps; values are the ones the apps were run with."""

# Baseline storyteller (user-study baseline condition, via baseline/main.py)
BASELINE_MODEL = "gpt-4o-mini"
# Director LLM behind the realtime voice apps (director, lenient and time-constrained modes)
REALTIME_DIRECTOR_MODEL = "gpt-4o-mini"
# OpenAI Realtime voice model
REALTIME_MODEL = "gpt-realtime"
# Story-so-far summarisation in Extensions-Demo
SUMMARY_MODEL = "gpt-4o-mini"
# Beat generator (custom stories from a topic) in Extensions-Demo
BEAT_GEN_MODEL = "gpt-4o"
