# Items to review manually (`cleanup/user-study-and-demos`)

None of these were changed, because each would change behaviour or needs your decision.

## Possible bugs
1. **Demo crashes on an unknown scenario.** In `Real-Time-API-Demo/server.py`, `on_start_session` and `reset_state()` fall back to the scenario key `olaf_anna_courtyard`, which no longer exists. Any unknown or missing key raises `KeyError`. Use a key from `NO_DERAILMENT_SCENARIOS` instead.
2. **`Implementation/baseline/main.py` as a CLI** (`run()` / `main()`) expects a scenario module with a single `SCENARIO`. Only the suite module exists, so the interactive baseline CLI fails. The study only imports its helpers, which work.
3. **Path fallback in the demo servers.** `IMPLEMENTATION_DIR` first tries `../Disney/Implementation` and then `../Implementation`. On a machine with a sibling `Disney/` checkout, the demos would silently import *that* code.

## Analysis and figures
4. **`make_plots_hq.py` writes to `plots/`, but the committed outputs are in `plots_hq/`** (pixel-identical). `plots_hq/q_resist_excl.png` isn't produced by any script.
5. **`make_plots_hq.py` hard-codes LLM-judge case-study scores** (`FROZEN_BASELINE`/`FROZEN_DIRECTOR`, used for `frozen_judge.png`). They don't match `evaluation_results/case_study_5x_results.json` on `master`; see `master`'s REVIEW.md.

## Data, privacy and licensing
6. `User-Study/outputs_all/` contains pseudonymous sessions, including the free text participants typed. Confirm the study consent covers sharing before anything leaves Disney/ETH.
7. **Git history** of this branch still contains the venvs, CoDi venv and `.wav` renders from its `master` ancestry (≈17k venv files, blobs up to 25 MB). Shrinking it needs a history rewrite and force-push, which I haven't done.
8. Olaf / Frozen character material is Disney IP. `socket.io.min.js` (MIT) is vendored in each `public/`.

## Design notes worth stating in the thesis
- Condition order is randomised with Python's unseeded `random`. Story 1 time limit: frontend-enforced. Story 2: server-enforced (both 5 min).
- The study baseline is a single `gpt-4o-mini` chat call per turn (temperature 0.7) with story history. Director conditions use `gpt-4o-mini` for the director and `gpt-realtime` for the voice.
