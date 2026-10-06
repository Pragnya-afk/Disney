# Olaf Interactive Storytelling: Extensions Demo

This branch builds on `user-study-and-demos` and adds an open-ended product demo on the same narrative core. It is the "future work / extensions" part of the controllable-storytelling Bachelor thesis.

**`Extensions-Demo/`** adds these features on top of the director agent:
- **Lenient director mode**: users can stop, skip ahead or ask for a summary. A consent state machine (`lenient/consent.py`), not the LLM, decides when a request is confirmed.
- **Beat generator**: turns a free-text story idea into a director-ready beat plan (`beat_generator/beat_generator.py`, `gpt-4o`). Users can edit the plan before starting.
- **Story-so-far summarisation**: older turns are folded into a running summary, so the director prompt stays bounded on long stories (`director_agent/story_summary.py`).
- **Second character**: Rocket Raccoon (`character_prompts/rocket.py`); built-in scenarios are re-voiced for the chosen character.
- **Time-constrained mode** with beat compression (`director_agent/beat_compression.py`).
- **Beat-stall pacing pressure**: escalating anti-stall text is appended in code after 2 / 3–4 / 5+ turns in one beat.
- **Story management**: end-of-story restart/switch and several story tabs per session.

`User-Study/` and the two `Real-Time-API-Demo*` apps are carried over from `user-study-and-demos`. Note that here they import this branch's modified `director_core.py` and `director_prompt.py`. To reproduce the study behaviour, use `user-study-and-demos`.

## Layout

```
Extensions-Demo/            server.py (Flask + Socket.IO + OpenAI Realtime), public/
Implementation/
  config.py                 model names (director, realtime, summary, beat generator, baseline)
  director_agent/           director_core.py, director_prompt.py, story_summary.py, beat_compression.py
    lenient/                lenient_director_core.py, consent.py
    time_constrained/       time_director_core.py
  beat_generator/           beat_generator.py
  character_prompts/        olaf.py, rocket.py
  scenarios/                olaf_derailment_scenario_suite.py
  time_control.py, audio_fx.py, baseline/main.py
User-Study/, Real-Time-API-Demo/, Real-Time-API-Demo-Time-Constrained/   carried over (see above)
```

## Setup and run

Requires **Python 3.12**.

```bash
make setup                           # .venv + pinned requirements.txt
source .venv/bin/activate
cp .env.example Implementation/.env  # OpenAI key with Realtime API access
make extensions                      # http://localhost:3004
```

Other targets are `make study-app` (:3003), `make demo` (:3000), `make demo-time` (:3002) and `make lint`. Override ports with `PORT=xxxx`.

Session logs and generated beat plans are written to `Extensions-Demo/outputs/` (gitignored).

### Models (`Implementation/config.py`)
| Role | Model |
|---|---|
| director (all modes) | `gpt-4o-mini` |
| story summariser | `gpt-4o-mini` |
| beat generator | `gpt-4o` |
| voice | `gpt-realtime` |

## Notes

- **Opener guard**:
  - The director prompt bans repeating the previous turn's opening filler family ("Oh"/"Ooh"/"Well").
  - The ban is also injected into the tool result in code, and `strip_banned_opener` removes a repeated filler from the spoken text.
- Story IDs and generated-plan IDs are random (`uuid4`). Nothing in the app is seeded; LLM outputs are not deterministic.
