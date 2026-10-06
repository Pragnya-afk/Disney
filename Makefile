# One-command entry points. Run from the repository root.
PY ?= python3
IMPL = Implementation

.PHONY: setup reproduce tables figures study experiments evaluate demo demo-time study-app lint

setup:            ## create .venv and install pinned dependencies
	python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt

reproduce: tables figures study   ## rebuild all tables and figures from saved results (no API calls)

tables:           ## evaluation_summary/ tables from evaluation_results/
	cd $(IMPL) && $(PY) analysis/generate_summary_tables.py
	cd $(IMPL) && $(PY) experiments/evaluate_time_constrained.py --only tables

figures:          ## LLM-judge figures 01-03, 14-17
	cd $(IMPL) && $(PY) analysis/generate_baseline_vs_director_plot.py
	cd $(IMPL) && $(PY) analysis/generate_case_study_plots.py

study:            ## user-study dataset, statistics report and figures
	cd User-Study/analysis_full && $(PY) build_dataset.py && $(PY) run_stats.py \
	  && $(PY) make_plots.py && $(PY) make_plots_hq.py && $(PY) make_plot_09_10_11.py \
	  && $(PY) make_plot_12_beat_compression.py && $(PY) make_plot_13_15_story_all_measures.py \
	  && $(PY) make_plot_16_17_derailment_paired.py

experiments:      ## regenerate all transcripts and evaluations (OpenAI API, slow and billed; skips existing files)
	cd $(IMPL) && $(PY) experiments/run_complete_pipeline.py

evaluate:         ## LLM-judge evaluation only (skips existing results)
	cd $(IMPL) && $(PY) experiments/run_all_evals.py

demo:             ## realtime voice demo (director) on :3000
	cd Real-Time-API-Demo && $(PY) server.py

demo-time:        ## realtime voice demo (time-constrained director) on :3002
	cd Real-Time-API-Demo-Time-Constrained && $(PY) server.py

study-app:        ## user-study web app on :3003
	cd User-Study && $(PY) server.py

lint:
	black --check . && ruff check .
