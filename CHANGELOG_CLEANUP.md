# Cleanup changelog (`cleanup/extensions`)

The cleanup sits on top of `extensions` and doesn't change model calls, prompts, thresholds or app logic.

## Baseline (`2b6591be`)
- `extensions`, plus the uncommitted beat-stall pacing work from your working copy. That work touches:
  - `pacing_instruction_suffix`
  - `_with_pacing_pressure`
  - the prompt thresholds
  - `Extensions-Demo/public/index.html`
- The untracked evaluation scripts and results in the working copy belong to `master` and were moved into `cleanup/master`.
- The user-study analysis and data live on `cleanup/user-study-and-demos` and `cleanup/master`, not here.

## Changes
- **Shared files**: files byte-identical to `user-study-and-demos` (the three carried-over app servers, `audio_fx.py`, `baseline/main.py`, `time_control.py`) use the cleaned versions from `cleanup/user-study-and-demos`.
- **Config**: `Implementation/config.py` names the director, realtime, summary, beat-generator and baseline models. All apps import it, with unchanged values.
- **Lint and format**: removed unused imports; `black` (100 columns) + `ruff` (E/F/W) via `pyproject.toml`; replaced `.gitignore`.
- **Docstrings**: one-line docstrings on public functions; multi-paragraph ones collapsed.
- **Reproducibility**: pinned `requirements.txt` + lock file, pinned per-app requirements (`Extensions-Demo` included), `.python-version`, `.env.example`, `Makefile`.
- **Docs**: README rewritten; `REVIEW.md`.

## Verification
Baseline and cleaned commits were compared in throwaway copies with a mocked OpenAI client, a virtual clock, synchronous threads, and pinned UUIDs and socket IDs:
- **Extensions-Demo**: director, lenient and time-constrained modes with Olaf and Rocket, 12 turns each. Each turn fed a typed input, a realtime tool call and a realtime reply, which triggers summaries, consent handling and story endings. The run also covered beat generation, saving, switching, restarting, closing tabs and saving the session. All 48 model requests and 309 realtime messages are identical.
- **Other checks**: all 637 director, time-director and baseline prompts, both demo servers and the four-phase user-study run are identical.
