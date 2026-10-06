# Items to review manually

Found during the cleanup. None of these were changed, because each would change behaviour or results or needs a decision from you. They're sorted by importance.

## A. Results and reproducibility

1. **Figures 11–13 cannot be regenerated.** `evaluation_results/beats_vs_fulltext_director/` and `outputs/director_agent_fulltext/` were empty directories on the original machine. As a result, `analysis/generate_generalization_beats_plots.py` fails, and so do the tables in `thesis_snippets/llm_judge/generalization_and_beats_ablation_section.tex`. Recover the data from backups or the machine that produced them.
2. **The case-study figures (14, 15) use hard-coded values that don't match the stored results.**
   - `analysis/generate_case_study_plots.py` hard-codes `FROZEN_BASELINE`, `FROZEN_DIRECTOR`, … and says they are the 5-run means from `evaluation_results/case_study_5x_results.json`.
   - The JSON's `average` values differ. For example, Frozen director Overall is 8.67 in the script but 9.0 in the JSON; Frozen baseline Plot is 3.44 vs. 4.0.
   - The same constants are copied in `User-Study/analysis_full/make_plots_hq.py` (`frozen_judge.png`).
   - Check which numbers are in the thesis.
3. **No script produces figures 04–07** (director vs. CoDi, time-budget ablation), and none exists anywhere in git history. Only the PNGs exist.
4. **The `Implementation/plots/` copies of 03, 14 and 15 differ from `evaluation_summary/plots/`.** All other copies are identical. Make sure the thesis uses the intended version.
5. **The Rocket generalization runs used an Olaf-specific actor prompt.** `director_agent/actor_common.py` contains "The response must sound like Olaf…" and "generic Olaf filler". `experiments/run_director_suite_rocket.py` reuses that prompt for Rocket, which may confound the second-character result.
6. **`evaluate_time_constrained.py --only qual` and `legacy/comparison_analysis.py` fail.** They import `evaluation_agent/evaluation_prompts_time.py` and `comparison_prompts.py`, which were deleted in commit `e7a06472`. Their prompts are *not* identical to the ones now in `evaluation_prompts.py`. To make these scripts run as originally, restore the files with:
   `git show e7a06472~1:Implementation/evaluation_agent/evaluation_prompts_time.py > Implementation/evaluation_agent/evaluation_prompts_time.py`
   Also confirm which prompt version produced `evaluation_results/time_constrained/*/qualitative_scores.json`.
7. **Output paths that don't match where the committed files live:**
   - `User-Study/analysis_full/make_plots_hq.py` writes to `plots/`, but the committed files are in `plots_hq/` (pixel-identical).
   - `plots_hq/q_resist_excl.png` isn't produced by any script.
8. **`evaluation_summary/all_runs_flat.csv` stores absolute paths** (`/home/prachakonda/Disney/...`). It is rewritten with the local path on every regeneration.
9. **Inconsistent judge default.** `evaluation_agent/evaluation_core.py` defaults to `--model gpt-5.5` (`config.EVALUATION_CORE_CLI_MODEL`), while every batch evaluation used `gpt-4o`.

## B. Broken entry points (pre-existing, kept as-is)

These fail identically before and after the cleanup.

| Script | Error | Likely fix |
|---|---|---|
| `analysis/generate_audio.py`, `director_agent/realtime_main.py`, `director_agent/time_constrained/time_realtime_main.py` | `ImportError: apply_fx` from `audio_fx` | `apply_fx` and `OLAF_AUDIOFX_CONFIG` were moved out of `audio_fx.py` into the demo servers in `f9b3a7c5`; move them back |
| `baseline/auto_main.py`, `baseline/main.py`, `baseline/runner.py`, `director_agent/main.py`, `director_agent/runner.py` | `module ... has no attribute 'SCENARIO'` | the single-scenario modules no longer exist; add `--scenario-name` as in `director_agent/auto_main.py` |
| `director_agent/time_constrained/time_strict_auto_main.py` | `No module named 'time_control'` | `IMPLEMENTATION_DIR` is one directory too shallow (file was moved into `time_constrained/`) |
| `legacy/comparison_analysis.py`, `legacy/comparison_batch_runner.sh` | missing `evaluation_agent.comparison_prompts` / `comparison_evaluator` | superseded; delete or restore from history |
| Realtime demos | `reset_state()` / `start_session` default to scenario `olaf_anna_courtyard`, which no longer exists | only reached if the browser sends no scenario key |

## C. Code that may not do what was intended

- `text_indicates_next_beat` (keyword beat-completion heuristic) only knows Red Riding Hood beat names, so it never fires for the other 12 stories.
- `time_auto_main.py` sleeps between turns to simulate user delays, so scripted time-constrained runs take real wall-clock time.
- Interactive and realtime runs use `gpt-4o-mini` for the director, while scripted runs use `gpt-5.5` (see `config.py`). Make sure the thesis states this.

## D. Data, privacy and licensing

- **Git history still contains** the vendored venvs, `.wav`/`.fbx` files and logs (the `.git` folder is ~210 MB). Commit `8e80714a` on `extensions` also contains raw user-study session JSONs. Removing them from history needs a rewrite (e.g. `git filter-repo`) and a force-push to the Disney GitLab remote. I haven't done this.
- `Implementation/outputs/target_duration_director_agent/complete_derail_red_riding_hood/2.0min/interactive/interactive_olaf_child_v5.wav` (6.7 MB) is a recorded session and may contain a real person's voice. It was left in place because `outputs/` is read-only per your instructions.
- `User-Study/outputs_all/` holds pseudonymous sessions with participants' free-text inputs. Confirm this is covered by the study consent before sharing outside Disney/ETH.
- Characters: Olaf / Frozen (Disney) and Rocket Raccoon (Marvel) prompts and story beats. Third-party licences: CoDi (MIT), AIDungeon (MIT, not used by any code; consider removing), `socket.io.min.js` (MIT, vendored in each `public/`).
- CoDi was modified locally (see `third_party/README.md`). The thesis should say so when reporting the CoDi baseline.

## E. Housekeeping

- `.gitattributes` normalises line endings, so `third_party/AIDungeon-develop/data/upwork.csv` shows as modified right after checkout. It's harmless: run `git checkout -- <file>` or remove the vendored AIDungeon copy.
- `legacy/` scripts write to an older `evaluation_results/<scenario>/` layout. Delete them once you no longer need them for provenance.
- The `Implementation/plots/` figure copies and both Overleaf packages under `thesis_snippets/` are copies. Keep them or drop them as you prefer.
