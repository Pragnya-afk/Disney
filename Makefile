# One-command entry points. Run from the repository root.
PY ?= python3

.PHONY: setup study-app demo demo-time analysis lint

setup:        ## create .venv and install pinned dependencies
	python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt

study-app:    ## user-study web app on :3003
	cd User-Study && $(PY) server.py

demo:         ## realtime voice demo (director) on :3000
	cd Real-Time-API-Demo && $(PY) server.py

demo-time:    ## realtime voice demo (time-constrained director) on :3002
	cd Real-Time-API-Demo-Time-Constrained && $(PY) server.py

analysis:     ## rebuild the study dataset, statistics report and figures from outputs_all/ (no API calls)
	cd User-Study/analysis_full && $(PY) build_dataset.py && $(PY) run_stats.py \
	  && $(PY) make_plots.py && $(PY) make_plots_hq.py && $(PY) make_plot_09_10_11.py \
	  && $(PY) make_plot_12_beat_compression.py && $(PY) make_plot_13_15_story_all_measures.py \
	  && $(PY) make_plot_16_17_derailment_paired.py

lint:
	black --check . && ruff check .
