# Cleanup changelog (`cleanup/master`)

The cleanup sits on top of `master` and doesn't change model calls, prompts, hyperparameters or results. See **Verification** at the end.

## Baseline (`90b7e976`)
- Starting point: `master`, plus `stash@{0}` (director anti-stall pacing fix, evaluation re-runs), plus the thesis work that was only in the local working copy:
  - full-text ablation code
  - Rocket and judge-comparison scripts
  - plots and results
  - user-study analysis
  - `.tex` sections
- It is committed as-is so every later step is a reviewable diff.

## Structure
- Stopped tracking the vendored virtualenvs (`Implementation/venv`, `Real-Time-API/venv`, CoDi's `venv`; ~10k files), `__pycache__`, `*.log` and the `.wav`/`.fbx` binaries.
- Removed `Real-Time-API/` and `Real-Time-API-Time-Constrained/`, which the `-Demo` apps (newer UI) replace.
- Removed the unused Node prototype (`server.js`, `package*.json`, old ReadMe) from `Real-Time-API-Demo/`, because the page only talks to the Python server.
- Moved `CoDi-main/` and `AIDungeon-develop/` to `third_party/` (code unchanged), updated the CoDi paths and added `third_party/README.md`.
- User study:
  - Removed the June pilot sessions in `User-Study/outputs/`.
  - Kept only the cleaned sessions in `outputs_all/phase_*`; duplicate restarts stay excluded.
  - Added the analysis code and the figure-12 script.
- Grouped the top-level scripts:
  - `Implementation/experiments/`: generation and evaluation
  - `Implementation/analysis/`: figures and tables
  - `Implementation/legacy/`: superseded or broken one-offs
  
  Each moved script resolves `Implementation/` the same way as before, so the relative/absolute paths written into result files are unchanged.
- Moved the old READMEs and notes to `docs/`, and the `.tex` sections and Overleaf packages to `thesis_snippets/`.
- Moved `FULL_STORY_TEXT` from a script into `scenarios/red_riding_hood_full_text.py` (byte-identical), because the director module imported it from a script.

## Readability
- Removed unused imports and variables, commented-out code, and f-strings without placeholders.
- Added `director_agent/actor_common.py` for actor prompts and helpers that were copy-pasted across up to six runners. Only definitions with identical ASTs were merged; variants that differ stay in their files.
- Added one-line docstrings to public functions, collapsed multi-paragraph function docstrings, and added obvious type hints. Module docstrings (usage) are kept.

## Configuration
- `Implementation/config.py` names every model used: baseline, scripted director, interactive, realtime, judge, CoDi, embeddings. All scripts and apps import from it, with identical values.
- `.env.example` documents `OPENAI_API_KEY` and `PORT`. `.env` stays gitignored, and no secrets are in the tree.
- Rewrote `.gitignore`.

## Reproducibility
- `requirements.txt` pins the direct dependencies to the thesis environment (adding `tabulate`, which pandas needs for Markdown tables). `requirements-lock.txt` has the full freeze. The app requirement files are pinned too.
- `.python-version` (3.12) and `pyproject.toml`.
- `Makefile`: `make reproduce` rebuilds all tables and figures without API calls. There are also targets for `experiments`, `evaluate`, the demos and the study app.

## Formatting
- `black` (line length 100) and `ruff` (E, F, W; E402/E501 ignored, see `pyproject.toml`). Import sorting is deliberately not applied, because several imports depend on preceding `sys.path` setup.

## Docs
- New `README.md`: purpose, setup, how to run, layout, and a map from thesis results to scripts and data.
- `REVIEW.md`: issues that need your decision.

## Verification
- **Behaviour.** A harness ran 60 entry points on the baseline commit and on each cleanup commit in throwaway copies:
  - all experiment, evaluation and analysis scripts
  - the interactive and scripted runners
  - all three web servers, through the Flask test client and the director-tool path
  
  The OpenAI client was replaced by a deterministic recorder and time by a virtual clock. Across all 15,238 recorded model requests (model, messages, temperature and so on), the exit codes and the 1,789 produced or modified files are identical before and after. Only paths in tracebacks of scripts that were already broken differ.
- **Results.** Re-running the analysis on the archived data reproduces every summary table and the study statistics byte for byte. Every regenerable figure is pixel-identical to the committed PNG (only the PNG metadata differs).
