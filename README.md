# Olaf Interactive Storytelling: User Study and Live Demos

This branch of the controllable-storytelling Bachelor thesis holds everything needed to run the **live** apps and to reproduce the **user-study analysis**:

- **`User-Study/`**: the participant-facing study, plus its analysis and the cleaned session data.
  - Story 1 (Frozen): baseline vs. director.
  - Story 2 (Cinderella): director vs. time-constrained director.
  - Two rounds per story in randomised order, with a questionnaire after each round.
- **`Real-Time-API-Demo/`**: a voice demo of the director-driven storyteller (scenario picker, beat tracker, Olaf voice effects).
- **`Real-Time-API-Demo-Time-Constrained/`**: the same demo with a target story duration and pacing-aware beat compression.

All three are Flask + Socket.IO apps that use OpenAI's Realtime API and share the narrative logic in `Implementation/`. The scripted experiments and the LLM-as-judge evaluation are on `master`.

## Repository layout

```
Implementation/                          shared narrative logic (imported by all three apps via sys.path)
  config.py                              model names (baseline, director, realtime)
  director_agent/director_core.py        director prompt + decision call, opener guard
  director_agent/director_prompt.py      director system prompt and rules
  director_agent/time_constrained/time_director_core.py   time-aware director
  baseline/main.py                       baseline condition (single chat call per turn)
  character_prompts/olaf.py              Olaf's character definition
  scenarios/olaf_derailment_scenario_suite.py   beat plans (13 stories x 7 derailment variants)
  time_control.py                        TemporalMonitor: pacing modes for a target duration
  audio_fx.py                            pitch/reverb chain for the demo voice
User-Study/
  server.py, public/                     study app (one Session object per participant)
  outputs_all/phase_*/                   cleaned session files used in the analysis (pseudonymous)
  analysis_full/                         dataset builder, statistics and figures
Real-Time-API-Demo/                      server.py, public/
Real-Time-API-Demo-Time-Constrained/     server.py, public/
thesis_snippets/user_study/              results section, appendix (prompts + beats), Overleaf package
```

## Setup

Requires **Python 3.12**.

```bash
make setup                          # python3.12 -m venv .venv && pip install -r requirements.txt
source .venv/bin/activate
cp .env.example Implementation/.env # add an OpenAI key with Realtime API access
```

`requirements.txt` pins the versions used during the study, and `requirements-lock.txt` is the full freeze. Each app also has its own pinned `requirements.txt` if you prefer one virtualenv per app.

## Run

| Command | What | URL |
|---|---|---|
| `make study-app` | user study | http://localhost:3003 |
| `make demo` | director voice demo | http://localhost:3000 |
| `make demo-time` | time-constrained voice demo | http://localhost:3002 |
| `make analysis` | rebuild the study dataset, stats report and figures (no API calls) | — |

Override ports with `PORT=xxxx`. All three apps can run side by side.

### User study flow
- Story 1: Olaf retells **Frozen** in two 5-minute rounds, baseline and director in random order.
- Story 2: Olaf retells **Cinderella** in two 5-minute rounds, director and time-constrained in random order.
- A questionnaire follows every round.
- Each participant's transcripts and answers go to `User-Study/outputs/session_<timestamp>_<sid>.json`.
- Condition order is drawn with Python's unseeded `random`, by design.

### Models
`Implementation/config.py`:
- director: `gpt-4o-mini`
- study baseline: `gpt-4o-mini` at temperature 0.7
- voice: `gpt-realtime`

## Scenario suite

`scenarios/olaf_derailment_scenario_suite.py` defines 13 base stories, each in 7 matched variants (`make_variant`):

| Variant | User inputs |
|---|---|
| `no_derailment` | on-topic throughout |
| `medium_derailment` / `complete_derailment` | random off-topic questions (every second turn / every turn) |
| `medium_adversarial` / `complete_adversarial` | jailbreak attempts: prompt injection, identity attacks |
| `medium_targeted` / `complete_targeted` | coherent attempts to stop the story, including direct instructions to the director |

Medium variants replace every second input, starting at the second turn, so the story always starts cleanly. The live apps use the `no_derailment` variants.

## Study analysis → thesis

All of these run from `User-Study/analysis_full/` (or `make analysis`) and read only `outputs_all/phase_*/*.json`:

| Output | Script | Used in |
|---|---|---|
| `phases.csv`, `participants.csv` | `build_dataset.py` (latest session per participant; restarts excluded) | all of the below |
| `stats_report.txt` | `run_stats.py` | results tables, statistics |
| `plots/01`–`08` | `make_plots.py` | fig. 05 (all conditions) |
| `plots/09`–`11` | `make_plot_09_10_11.py` | fig. 10, 11 (pacing, ending) |
| `plots/12` | `make_plot_12_beat_compression.py` | fig. 12 (beat compression) |
| `plots/13`, `15` | `make_plot_13_15_story_all_measures.py` | Story 1 / Story 2 measures |
| `plots/16`, `17` | `make_plot_16_17_derailment_paired.py` | paired derailment resistance |
| `plots_hq/*` | `make_plots_hq.py` (writes to `plots/`; the committed copies are in `plots_hq/`) | presentation figures |

The section text is in `thesis_snippets/user_study/results_section.tex`.

## Implementation notes

- **Opener guard**:
  - The director prompt bans repeating the previous turn's opening word or filler exclamation family ("Oh"/"Ooh"/"Well").
  - Each app also injects the ban into the tool result in plain code, and `strip_banned_opener` removes a repeated filler from the output, because LLM compliance alone proved unreliable.
- **Pacing**: the time-constrained director gets a `pacing_mode` from `TemporalMonitor` (`too_fast` / `normal` / `hurry` / `critical` / `final`) and compresses or expands beats to end near the time limit.
- Session logs under each app's `outputs/` are gitignored; only the cleaned study data in `outputs_all/` is versioned.
