# Cleanup changelog (`cleanup/user-study-and-demos`)

The cleanup sits on top of `user-study-and-demos` and doesn't change model calls, prompts, timings or study logic.

## Baseline (`ec1cfec0`)
- The branch as-is, plus the study material that existed only in the local working copy:
  - `User-Study/analysis_full/`: dataset builder, statistics, figures
  - the cleaned sessions in `User-Study/outputs_all/phase_*` (duplicate restarts excluded, pilot sessions not included)
  - the study `.tex` write-ups

## Changes
- **Structure**:
  - Moved the `.tex` write-ups and the Overleaf package to `thesis_snippets/user_study/`.
  - Replaced `.gitignore` (venvs, caches, `.env`, runtime session logs, local-only material).
- **Lint and format**:
  - removed unused imports
  - split a multi-import line
  - renamed an ambiguous variable
  - `black` (100 columns) + `ruff` (E/F/W), configured in `pyproject.toml`
- **Config**: `Implementation/config.py` names the baseline, realtime-director and realtime voice models. All three apps import it, and the values are unchanged.
- **Docstrings**: one-line docstrings on public functions; multi-paragraph ones collapsed. The derailment-variant description moved from `make_variant` into the README.
- **Reproducibility**:
  - pinned `requirements.txt` (+ `requirements-lock.txt`) and pinned per-app requirements
  - `.python-version`, `.env.example`
  - `Makefile`: `study-app`, `demo`, `demo-time`, `analysis`, `lint`
- **Docs**:
  - The README was rewritten. The old one said Story 2 rounds last 3 min and the baseline gets no story history; the code uses 5 min and passes the story so far.
  - New sections map the analysis scripts to the thesis figures.
  - `REVIEW.md` lists issues that need a decision.

## Verification
The harness compared the baseline and cleaned commits in throwaway copies:
- **Prompts**: every director, time-director and baseline prompt for all 91 scenarios at three story states (637 prompts) is identical.
- **Demo servers**: HTTP routes, scenario registry, system prompts, and 12 director-tool calls per demo with a mocked OpenAI client. Identical requests and websocket payloads.
- **Study app**: a full session through all four counterbalanced phases via the Socket.IO test client, with a fake realtime websocket, synchronous threads and pinned socket IDs. Identical model requests (20), realtime messages (48), questionnaires and session file.
- **Analysis**: all eight analysis scripts give identical `phases.csv`, `participants.csv` and `stats_report.txt`, and identical figures.
