# Controllable Storytelling for Interactive AI Characters

Code, data and analysis for the Bachelor thesis on keeping an LLM-driven character (Olaf, and Rocket Raccoon as a second character) on a planned story while users interrupt, derail or try to jailbreak it.

The core idea is a **director agent**: a second LLM that sees the story plan (a list of *beats*), the story so far and the user's latest input. It decides how the character (the *actor*) should respond and when a beat is complete. The thesis compares it with:

- a single-call **baseline** storyteller
- the **CoDi** multi-agent framework
- a **time-constrained** director that paces the story to a target duration

It evaluates them with an **LLM-as-judge** and a live **user study**.

## Repository layout

```
Implementation/                 research code (run everything from this folder)
  config.py                     all model names used in the thesis
  character_prompts/            Olaf and Rocket character definitions
  scenarios/                    beat plans + scripted user inputs (13 Olaf stories x 7 derailment levels, 7 Rocket variants)
  baseline/                     single-LLM baseline (auto_main.py: scripted, main.py: interactive)
  director_agent/               director + actor
    director_core.py            director prompt, decision call, anti-stall pacing suffix, opener guard
    director_prompt.py          director system prompt and rules
    actor_common.py             actor prompt and shared helpers
    auto_main.py / main.py      scripted / interactive runner
    *_fulltext.py               ablation: director gets the full story text instead of beats
    time_constrained/           time-aware director + TemporalMonitor runners
    realtime_main.py            terminal voice client for the OpenAI Realtime API
  time_control.py               TemporalMonitor (pacing modes for a target duration)
  audio_fx.py                   pitch/reverb effect chain for the character voice
  evaluation_agent/             LLM-judge prompts, AB/BA pairwise + single-story scoring, table builder
  experiments/                  drivers that generate transcripts and run evaluations
  analysis/                     figures/tables from saved results (no API calls)
  legacy/                       superseded one-off scripts, kept for provenance (some no longer run)
  outputs/                      generated story transcripts (data)
  evaluation_results/           judge results (data)
  evaluation_summary/           summary tables (.csv/.md/.tex) and figures
  plots/                        copies of the figures used in the thesis
Real-Time-API-Demo/             browser voice demo: director agent (Flask + Socket.IO + OpenAI Realtime)
Real-Time-API-Demo-Time-Constrained/   same demo with the time-constrained director
User-Study/                     study web app (server.py, public/) and analysis
  outputs_all/phase_*/          cleaned, pseudonymised session files used in the analysis
  analysis_full/                dataset builder, statistics and figures
thesis_snippets/                LaTeX sections/tables written for the thesis (+ Overleaf packages)
docs/                           earlier design notes and READMEs
third_party/                    CoDi (baseline) and AIDungeon (reference), see third_party/README.md
```

## Setup

Requires **Python 3.12** (see `.python-version`).

```bash
make setup                       # python3.12 -m venv .venv && pip install -r requirements.txt
source .venv/bin/activate
cp .env.example Implementation/.env   # then put your OpenAI key in it
```

`requirements.txt` pins the direct dependencies to the versions used for the thesis. `requirements-lock.txt` is the full `pip freeze` of that environment. The realtime apps also have their own pinned `requirements.txt`.

## How to run

| Goal | Command | API key needed |
|---|---|---|
| Rebuild all tables and figures from the saved results | `make reproduce` | no |
| Only the LLM-judge tables / figures | `make tables` / `make figures` | no |
| Only the user-study dataset, stats and figures | `make study` | no |
| Regenerate all transcripts and evaluations | `make experiments` | yes (slow, billed) |
| Re-run only the LLM-judge evaluation | `make evaluate` | yes |
| Voice demo (director) on http://localhost:3000 | `make demo` | yes, Realtime API |
| Voice demo (time-constrained) on http://localhost:3002 | `make demo-time` | yes, Realtime API |
| User-study app on http://localhost:3003 | `make study-app` | yes, Realtime API |

Single runs, from `Implementation/`:

```bash
# one scripted director story
python director_agent/auto_main.py --character character_prompts.olaf \
  --scenario scenarios.olaf_derailment_scenario_suite \
  --scenario-name olaf_retells_cinderella_medium_derailment --run-id 1

# same story with a 5-minute target duration
python director_agent/time_constrained/time_auto_main.py --character character_prompts.olaf \
  --scenario scenarios.olaf_derailment_scenario_suite \
  --scenario-name olaf_retells_cinderella_medium_derailment --time-limit 5 --run-id 1

# interactive terminal session (type 'quit' to stop)
python director_agent/time_constrained/time_main.py --character character_prompts.olaf \
  --scenario scenarios.olaf_derailment_scenario_suite \
  --scenario-name olaf_retells_cinderella_no_derailment --time-limit 5
```

All experiment scripts skip outputs that already exist, so they can be interrupted and restarted. Most accept `--dry-run`.

`make experiments` runs the core Olaf pipeline: baseline, director, time-constrained, CoDi, then all judge tracks. The CoDi phase calls `third_party/CoDi-main/CoDi-main/generation.py`, which needs CoDi's own dependencies. The other studies have their own drivers in `Implementation/experiments/`:

| Script | What it does |
|---|---|
| `run_baseline_suite.py`, `run_full_suite.py` | baseline / director + time-constrained (0.5, 2, 5, 10 min) transcripts for the Olaf suite |
| `run_baseline_suite_rocket.py`, `run_director_suite_rocket.py`, `run_rocket_evals.py` | second-character (Rocket) generation and evaluation |
| `run_baseline_fulltext_rrh.py`, `run_director_fulltext_suite_rrh.py`, `run_director_beats_vs_fulltext_evals.py` | beats vs. full-text ablation |
| `run_frozen_cinderella_full_eval.py`, `regen_case_study_5x.py` | the two user-study stories through the judge pipeline; 5-run case study |
| `regen_complete_derailment_director.py`, `regen_medium_derailment_director.py` | one-off re-generation after the anti-stall pacing fix |
| `run_all_evals.py`, `evaluate_time_constrained.py`, `run_codi_eval.py` | judge evaluation tracks and time-constrained metrics |
| `run_judge_model_comparison.py`, `run_judge_model_comparison_baseline.py` | re-judge selected pairs with another judge model |
| `run_codi_interactive.py`, `run_codi_suite_and_compare.py`, `run_complete_pipeline.py` | CoDi runs and end-to-end pipeline |

### Reproducibility notes

- Model names live in `Implementation/config.py`:
  - baseline: `gpt-4o-mini`
  - scripted director/actor: `gpt-5.5`
  - interactive/realtime director: `gpt-4o-mini`
  - judge: `gpt-4o`
- Sampling:
  - The judge runs at temperature 0, except in `run_judge_model_comparison*.py`, where `gpt-5.x` judges only accept the default temperature.
  - The baseline runs at temperature 0.7.
  - The director and actor calls use the API default.
- No random seeds are used. OpenAI outputs are not deterministic, so regenerated transcripts will differ from the archived ones in `outputs/`.
- Everything downstream of the archived transcripts is deterministic: running `make reproduce` gives byte-identical tables and pixel-identical figures.
- The user-study app randomises condition order per participant with Python's unseeded `random`, by design.

## Thesis results → scripts

| Thesis part | Figures / tables | Produced by | Data |
|---|---|---|---|
| LLM judge: baseline vs. director | fig. 01, 02, 03, 16, 17; `table_*` | `analysis/generate_baseline_vs_director_plot.py`, `analysis/generate_summary_tables.py` | `evaluation_results/baseline_vs_director/` |
| LLM judge: director vs. CoDi | fig. 04, 05 | *no script in repo (see REVIEW.md)* | `evaluation_results/` (CoDi tracks), `third_party/CoDi-main/CoDi-main/outputs/` |
| Time-budget ablation | fig. 06, 07; time tables | `experiments/evaluate_time_constrained.py` (tables); figures: *no script in repo* | `evaluation_results/time_constrained/` |
| Second character (Rocket) | fig. 08–10 | `analysis/generate_generalization_beats_plots.py` | `evaluation_results/baseline_vs_director/rocket_*` |
| Beats vs. full-text ablation | fig. 11–13 | `analysis/generate_generalization_beats_plots.py` | `evaluation_results/beats_vs_fulltext_director/` *(missing, see REVIEW.md)* |
| Case study (judge, 5 runs) | fig. 14, 15 | `experiments/regen_case_study_5x.py` → `analysis/generate_case_study_plots.py` | `evaluation_results/case_study_5x_results.json` |
| Judge-model robustness | `thesis_snippets/llm_judge/judge_model_comparison_tables.tex` | `experiments/run_judge_model_comparison*.py` | `evaluation_results/*/eval_run_1_gpt-5.6-sol.json` |
| User study: Story 1, Story 2, all conditions | study fig. 05, 10–13, 15–17 | `User-Study/analysis_full/make_plot*.py` | `User-Study/analysis_full/phases.csv` (from `build_dataset.py`) |
| User study: statistics | `analysis_full/stats_report.txt` | `User-Study/analysis_full/run_stats.py` | same |
| Appendix: beats and prompts | `thesis_snippets/user_study/appendix_prompts_and_beats.tex` | hand-written from `scenarios/`, `director_agent/`, `User-Study/server.py` | — |

The figure numbers are the file-name prefixes in `Implementation/evaluation_summary/plots/` and `User-Study/analysis_full/plots/`.

## Data and confidentiality

- `User-Study/outputs_all/` holds the cleaned study sessions used in the analysis. Participants are identified only by random session IDs. The free-text inputs are what participants typed to the character. Pilot sessions and duplicate restarts are excluded.
- Character prompts reference Disney (Olaf / Frozen) and Marvel (Rocket Raccoon) characters. Check the rights situation before publishing outside the original context.
- API keys are read from `Implementation/.env` (gitignored). No key is committed.

## Tooling

`make lint` runs `black --check` and `ruff`. The configuration lives in `pyproject.toml`.
