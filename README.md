# Olaf Interactive Storytelling — User Study & Demos

This branch contains only what's needed to run the three live apps:

- **`User-Study/`** — the full participant-facing study (Story 1: Frozen, baseline vs. director; Story 2: Cinderella, director vs. time-constrained), with questionnaires and session logging.
- **`Real-Time-API-Demo/`** — a standalone voice demo of the director-driven storytelling agent (multiple scenarios, beat tracking, audio effects).
- **`Real-Time-API-Demo-Time-Constrained/`** — the same, but under a target time limit with pacing-aware beat compression.

All three are Flask + Socket.IO apps that talk to OpenAI's Realtime API, sharing a small set of narrative-logic modules under `Implementation/`.

## Repo layout

```
Implementation/                          shared narrative logic (imported by all three apps)
  director_agent/
    director_core.py                     director LLM call + prompt builder
    director_prompt.py                   static director instructions
    time_constrained/time_director_core.py   time-aware director variant
  baseline/main.py                       no-director baseline condition (User-Study only)
  character_prompts/olaf.py              Olaf's character definition
  scenarios/olaf_derailment_scenario_suite.py   story beat structures
  time_control.py                        TemporalMonitor (pacing for time-constrained mode)
  audio_fx.py                            audio effects chain (voice demos only)

User-Study/                              server.py, public/, requirements.txt
Real-Time-API-Demo/                      server.py, public/, requirements.txt
Real-Time-API-Demo-Time-Constrained/     server.py, public/, requirements.txt
```

Each app is self-contained (its own `requirements.txt`, own `public/` frontend) and reaches into `Implementation/` via `sys.path` at startup — there's no separate install step for `Implementation/` itself.

## Prerequisites

- Python 3.12 (also works on other recent 3.x versions)
- An OpenAI API key with access to the Realtime API (`gpt-realtime`) and `gpt-4o-mini`

## Setup (per app)

Each app needs its own virtualenv (or at least its own `pip install`) and its own `.env` file with:

```
OPENAI_API_KEY=sk-...
```

### 1. User-Study

```bash
cd User-Study
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
echo "OPENAI_API_KEY=sk-..." > .env
python3 server.py
```

Runs on `http://localhost:3003` by default (override with `PORT=xxxx`). Open that URL in a browser to start the study flow: Story 1 (Frozen, 2 rounds, baseline vs. director, 5 min each) → Story 2 (Cinderella, 2 rounds, director vs. time-constrained, 3 min each), with a questionnaire after every round. Session transcripts + questionnaire responses are saved to `User-Study/outputs/session_<timestamp>.json`.

### 2. Real-Time-API-Demo

```bash
cd Real-Time-API-Demo
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
echo "OPENAI_API_KEY=sk-..." > .env
python3 server.py
```

Runs on `http://localhost:3000` by default. Lets you pick a scenario and play through it with the director-driven voice agent. Session logs land in `Real-Time-API-Demo/outputs/`.

### 3. Real-Time-API-Demo-Time-Constrained

```bash
cd Real-Time-API-Demo-Time-Constrained
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
echo "OPENAI_API_KEY=sk-..." > .env
python3 server.py
```

Runs on `http://localhost:3002` by default. Same as above, but with a selectable target time limit — the director paces the story (`pacing_mode`: `too_fast` / `normal` / `hurry` / `critical` / `final`) to land the ending close to that limit. Logs land in `Real-Time-API-Demo-Time-Constrained/outputs/`.

## Running more than one at once

Each server defaults to its own port — `Real-Time-API-Demo`: 3000, `Real-Time-API-Demo-Time-Constrained`: 3002, `User-Study`: 3003 — so all three can run side by side in separate terminals/venvs without conflicting. Override any of them with `PORT=xxxx python3 server.py`.

## Notes

- `outputs/` directories are gitignored except for a `.gitkeep` placeholder — session logs are generated at runtime and shouldn't be committed.
- `Implementation/baseline/main.py`'s `build_prompt` intentionally gives the baseline condition *only* the character prompt and the beat list (no story history) — this is a deliberate simplification for a clean baseline-vs-director comparison, not a bug.
- The director's "Opener Guard" mechanism (in `director_core.py` / injected into each app's `handle_director_tool`) deterministically bans repeating the previous turn's opening word/filler exclamation family (e.g. "Oh"/"Ooh"/"Well") — this is enforced in plain code in the tool-result payload, not left to the director LLM's own compliance, since that proved unreliable in testing.
