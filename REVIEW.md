# Items to review manually (`cleanup/extensions`)

None of these were changed.

1. **Carried-over apps run a different director than the study.** `User-Study/` and both `Real-Time-API-Demo*` apps import this branch's modified `director_core.py` and `director_prompt.py`. The pacing thresholds also differ: here pressure starts at turn 2, while on `user-study-and-demos` it starts at turn 4. On this branch they don't reproduce the study behaviour. Consider removing them from `extensions` or documenting this.
2. **Uncommitted work.** The beat-stall pacing changes from 2026-09-28 were uncommitted in your working copy. They are committed on `cleanup/extensions` only; your original `extensions` branch is unchanged.
3. **History.** Commit `8e80714a` added raw user-study session JSONs (`user_study_outputs_disney/`), and `b84dbb93` deleted them, but they remain in the history pushed to the Disney GitLab. History from `master` also still contains venvs and `.wav` files. Removing them needs `git filter-repo` + force-push.
4. **Demo crashes on an unknown scenario.** In `Real-Time-API-Demo/server.py`, an unknown scenario falls back to the non-existent key `olaf_anna_courtyard` (`KeyError`). Same issue as on `user-study-and-demos`.
5. **IP and licensing.** The Rocket Raccoon (Marvel) and Olaf (Disney) prompts are third-party IP. `socket.io.min.js` (MIT) is vendored in each `public/`.
6. **Persisted user text.** Generated beat plans and session logs under `Extensions-Demo/outputs/` include whatever users typed. They are gitignored, so don't force-add them.
