# One-command entry points. Run from the repository root.
PY ?= python3

.PHONY: setup extensions study-app demo demo-time lint

setup:        ## create .venv and install pinned dependencies
	python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt

extensions:   ## Extensions-Demo (lenient mode, beat generator, summaries, story tabs) on :3004
	cd Extensions-Demo && $(PY) server.py

study-app:    ## user-study web app on :3003
	cd User-Study && $(PY) server.py

demo:         ## realtime voice demo (director) on :3000
	cd Real-Time-API-Demo && $(PY) server.py

demo-time:    ## realtime voice demo (time-constrained director) on :3002
	cd Real-Time-API-Demo-Time-Constrained && $(PY) server.py

lint:
	black --check . && ruff check .
