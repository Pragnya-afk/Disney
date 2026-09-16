# Olaf Interactive Storytelling — Extensions Demo

This branch builds on `user-study-and-demos`, adding an open-ended product demo on top of the same shared narrative core.

- **`Extensions-Demo/`** — an open-ended demo adding story-so-far summarization, an LLM beat generator (custom scenarios from a topic instead of a fixed suite), a lenient director mode, end-of-story restart/switch, and multi-story tab switching.

## Repo layout

```
Implementation/                          shared narrative logic (imported by Extensions-Demo)
  director_agent/
    director_core.py                     director LLM call + prompt builder
    director_prompt.py                   static director instructions
    story_summary.py                     story-so-far summarization
    lenient/lenient_director_core.py     lenient director variant
    lenient/consent.py                   end-of-story consent handling
  beat_generator/beat_generator.py       LLM-generated custom scenarios from a topic
  character_prompts/olaf.py              Olaf's character definition
  scenarios/olaf_derailment_scenario_suite.py   story beat structures
  time_control.py                        TemporalMonitor (pacing for time-constrained mode)
  audio_fx.py                            audio effects chain

Extensions-Demo/                         server.py, public/, requirements.txt
```

The app is self-contained (its own `requirements.txt`, own `public/` frontend) and reaches into `Implementation/` via `sys.path` at startup — there's no separate install step for `Implementation/` itself.

## Prerequisites

- Python 3.12 (also works on other recent 3.x versions)
- An OpenAI API key with access to the Realtime API (`gpt-realtime`) and `gpt-4o-mini`

## Setup

```bash
cd Extensions-Demo
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
echo "OPENAI_API_KEY=sk-..." > .env
python3 server.py
```

Runs on `http://localhost:3004` by default (override with `PORT=xxxx`). Supports three modes per story (`director` / `lenient` / `time_constrained`), an LLM-generated beat suite from a custom topic (in addition to the fixed scenario suite), story-so-far summarization once a story runs long, end-of-story restart/switch, and multiple concurrent story tabs in one session. Logs land in `Extensions-Demo/outputs/`.

## Notes

- `outputs/` directories are gitignored except for a `.gitkeep` placeholder — session logs are generated at runtime and shouldn't be committed.
- The director's "Opener Guard" mechanism (in `director_core.py`, injected into `handle_director_tool`) deterministically bans repeating the previous turn's opening word/filler exclamation family (e.g. "Oh"/"Ooh"/"Well") — this is enforced in plain code in the tool-result payload, not left to the director LLM's own compliance, since that proved unreliable in testing.
