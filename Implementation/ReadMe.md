# Interactive AI Character Storytelling Implementations

This folder contains two storytelling implementations:

1. **Baseline**
2. **Director Agent Extension**

The goal is to first implement a simple beat-based storytelling baseline, then extend it with a Director Agent that handles interruptions and guides story progression more explicitly.

---

## Folder Structure

```text
Implementation/
│
├── .env
│
├── character_prompts/
│   ├── olaf.py
│   └── rocket.py
│
├── baseline/
│   ├── main.py
│   └── outputs/
│
└── director_agent/
    ├── main.py
    ├── director_agent.py
    ├── director_prompt.py
    └── outputs/
```

---

## Setup

Create a `.env` file inside the `Implementation/` folder:

```env
OPENAI_API_KEY=your_api_key_here
```

Install dependencies:

```bash
pip install openai python-dotenv
```

---

## Character Prompt Files

Character configuration is stored in:

```text
Implementation/character_prompts/
```

Each character file contains:

- `CHARACTER`
- `STORY_TOPIC`
- `BEATS`

Example files:

```text
character_prompts/olaf.py
character_prompts/rocket.py
```

To switch characters, edit the import line in the relevant `main.py` file.

For Olaf:

```python
from character_prompts.olaf import CHARACTER, STORY_TOPIC, BEATS
```

For Rocket:

```python
from character_prompts.rocket import CHARACTER, STORY_TOPIC, BEATS
```

---

# 1. Baseline Implementation

## Location

```text
Implementation/baseline/main.py
```

## Description

The baseline implementation uses a single LLM call per user turn.

The LLM directly acts as the character and is responsible for:

- responding to the user,
- staying in character,
- progressing the current story beat,
- selecting an animation,
- deciding whether the current beat is complete.

Flow:

```text
User input
   ↓
Character LLM
   ↓
Character response + animation + beat completion decision
   ↓
Story state update
```

## Run Baseline

From the `Implementation/` folder:

```bash
python baseline/main.py
```

Or:

```bash
python3 baseline/main.py
```

## Baseline Output

The transcript is saved to:

```text
Implementation/baseline/outputs/
```

Example:

```text
Implementation/baseline/outputs/baseline_transcript_olaf.json
```

---

# 2. Director Agent Implementation

## Location

```text
Implementation/director_agent/
```

Files:

```text
director_agent/main.py
director_agent/director_agent.py
director_agent/director_prompt.py
```

## Description

The director-agent implementation uses two LLM calls per user turn.

### Director Agent

The Director Agent does not speak as the character.

It decides:

- whether the user is helping the story,
- whether the user is interrupting,
- whether the system should answer and steer back,
- whether to gently redirect,
- whether the current beat should complete,
- whether the story should close.

### Actor Agent

The Actor Agent speaks as the character.

It receives the Director Agent’s decision and produces:

- the character response,
- the story event,
- selected animation,
- beat completion status.

Flow:

```text
User input
   ↓
Director Agent
   ↓
Director decision
   ↓
Actor Agent
   ↓
Character response + animation
   ↓
Story state update
```

This implementation is useful for testing interruption handling and stronger story steering.

## Run Director Agent Version

From the `Implementation/` folder:

```bash
python director_agent/main.py
```

Or:

```bash
python3 director_agent/main.py
```

## Director Agent Output

The transcript is saved to:

```text
Implementation/director_agent/outputs/
```

Example:

```text
Implementation/director_agent/outputs/director_agent_transcript_olaf.json
```

The transcript includes both:

- the Director Agent decision,
- the Actor Agent output.

---

## Output Transcript Format

Each transcript stores the interaction turn by turn.

Baseline transcript entries look like:

```json
{
  "method": "baseline",
  "character": "Olaf",
  "beat": "start",
  "user_input": "Hi Olaf!",
  "model_output": {
    "character_response": "...",
    "story_event": "...",
    "animation": "...",
    "beat_completed": false,
    "reason": "..."
  }
}
```

Director-agent transcript entries look like:

```json
{
  "method": "director_agent",
  "character": "Olaf",
  "beat": "start",
  "user_input": "Hi Olaf!",
  "director_decision": {
    "decision_type": "progress_story",
    "interruption_detected": false,
    "user_intent": "...",
    "director_instruction": "...",
    "should_progress_current_beat": true,
    "should_complete_beat": false,
    "reason": "..."
  },
  "actor_output": {
    "character_response": "...",
    "story_event": "...",
    "animation": "...",
    "beat_completed": false,
    "reason": "..."
  }
}
```

---

## Notes for Evaluation

These implementations are designed to be compared later.

Possible comparison dimensions:

- story completion,
- beat progression,
- character consistency,
- interruption handling,
- story coherence,
- animation validity,
- number of turns to complete the story,
- whether the story reaches resolution.

The output folders keep the transcripts separated:

```text
baseline/outputs/
director_agent/outputs/
```

This makes it easier to run an evaluation script later.

---

## Common Issues

### API key not found

Make sure `.env` exists here:

```text
Implementation/.env
```

and contains:

```env
OPENAI_API_KEY=your_api_key_here
```

### Import error for `character_prompts`

Run the scripts from inside the `Implementation/` folder:

```bash
cd Implementation
python baseline/main.py
```

or:

```bash
cd Implementation
python director_agent/main.py
```

### Invalid animation

The code validates animations. If the model invents an animation, the system falls back to the first available animation in the character prompt file.

---

## Current Implementations

| Method | Folder | Main File | Description |
|---|---|---|---|
| Baseline | `baseline/` | `baseline/main.py` | Single-agent beat-based storytelling |
| Director Agent | `director_agent/` | `director_agent/main.py` | Director handles interruptions and story steering |

---
# 3. Evaluation Agent

## Location

```text
Implementation/evaluation/
```

Files:

```text
evaluation/evaluation_agent.py
evaluation/evaluation_prompts.py
evaluation/run_eval.sh
evaluation_results/
```

## Description

The evaluation agent compares generated transcripts from different storytelling methods.

For the current setup, it compares:

```text
Baseline
vs
Director Agent
```

The evaluator can run:

1. **Single-story scoring**
   - Scores each story independently from 1 to 10.

2. **A/B side-by-side comparison**
   - Compares Story A and Story B directly.

3. **Optional AB/BA comparison**
   - Runs the comparison twice with the story order swapped.
   - This helps reduce order bias.
   - If AB and BA disagree, the final result is marked as `Same`.

## Evaluation Dimensions

The evaluator compares stories using these dimensions:

- Plot
- Development
- Language Use
- Interruption Handling
- Character Fidelity
- Narrative Control
- Overall

## Before Running Evaluation

First run both systems so their transcript files exist.

Run the baseline:

```bash
python baseline/main.py
```

Run the director-agent version:

```bash
python director_agent/main.py
```

This should create:

```text
Implementation/baseline/outputs/baseline_transcript_olaf.json
Implementation/director_agent/outputs/director_agent_transcript_olaf.json
```

## Run Evaluation with Shell Script

From the `Implementation/` folder:

```bash
bash evaluation/run_eval.sh
```

The shell script compares:

```text
baseline/outputs/baseline_transcript_olaf.json
director_agent/outputs/director_agent_transcript_olaf.json
```

using:

```text
character_prompts.olaf
```

## Run Evaluation Manually

From the `Implementation/` folder:

```bash
python evaluation_agent/evaluation_core.py \
  --story-a baseline/outputs/baseline_transcript_olaf.json \
  --story-b director_agent/outputs/director_agent_transcript_olaf.json \
  --character-module character_prompts.olaf \
  --out-dir evaluation_results \
  --model gpt-4o \
  --ab-ba
```

If your system uses `python3`:

```bash
python3 evaluation_agent/evaluation_core.py \
  --story-a baseline/outputs/baseline_transcript_olaf.json \
  --story-b director_agent/outputs/director_agent_transcript_olaf.json \
  --character-module character_prompts.olaf \
  --out-dir evaluation_results \
  --model gpt-4o \
  --ab-ba
```

## Evaluation Output

Evaluation results are saved to:

```text
Implementation/evaluation_results/
```

Example output file:

```text
Implementation/evaluation_results/evaluation_result_20260101_143022.json
```

The saved JSON includes:

- input transcript paths,
- evaluator model,
- single-story scores for Story A and Story B,
- AB comparison result,
- optional BA comparison result,
- aggregated AB/BA winners.

## Interpreting Story A and Story B

By default:

```text
Story A = baseline
Story B = director_agent
```

So if the evaluator says:

```text
Overall: B
```

that means the Director Agent version was judged better overall.

If you swap the command arguments, the meaning of A and B also swaps.

## Example Evaluation Result Structure

```json
{
  "story_a_path": "baseline/outputs/baseline_transcript_olaf.json",
  "story_b_path": "director_agent/outputs/director_agent_transcript_olaf.json",
  "character_module": "character_prompts.olaf",
  "model": "gpt-4o",
  "ab_ba_enabled": true,
  "single_story_scores": {
    "A": {
      "assessment": "...",
      "scores": {
        "Plot": 7,
        "Development": 6,
        "Language Use": 8,
        "Interruption Handling": 6,
        "Character Fidelity": 8,
        "Narrative Control": 6,
        "Overall": 7
      }
    },
    "B": {
      "assessment": "...",
      "scores": {
        "Plot": 8,
        "Development": 7,
        "Language Use": 8,
        "Interruption Handling": 9,
        "Character Fidelity": 8,
        "Narrative Control": 8,
        "Overall": 8
      }
    }
  },
  "ab_evaluation": {
    "assessment": "...",
    "winners": {
      "Plot": "B",
      "Development": "B",
      "Language Use": "Same",
      "Interruption Handling": "B",
      "Character Fidelity": "Same",
      "Narrative Control": "B",
      "Overall": "B"
    }
  },
  "aggregated_ab_ba_winners": {
    "Plot": "B",
    "Development": "B",
    "Language Use": "Same",
    "Interruption Handling": "B",
    "Character Fidelity": "Same",
    "Narrative Control": "B",
    "Overall": "B"
  }
}
```

## Evaluating Rocket Instead of Olaf

First make sure both `baseline/main.py` and `director_agent/main.py` import Rocket:

```python
from character_prompts.rocket import CHARACTER, STORY_TOPIC, BEATS
```

Then run both systems again to generate Rocket transcripts.

Update the evaluation command:

```bash
python evaluation_agent/evaluation_core.py \
  --story-a baseline/outputs/baseline_transcript_rocket.json \
  --story-b director_agent/outputs/director_agent_transcript_rocket.json \
  --character-module character_prompts.rocket \
  --out-dir evaluation_results \
  --model gpt-4o \
  --ab-ba
```

## Common Issues

### API key not found

Make sure `.env` exists here:

```text
Implementation/.env
```

and contains:

```env
OPENAI_API_KEY=your_api_key_here
```

### Import error for `character_prompts`

Run the scripts from inside the `Implementation/` folder:

```bash
cd Implementation
python baseline/main.py
```

or:

```bash
cd Implementation
python director_agent/main.py
```

### Invalid animation

The code validates animations. If the model invents an animation, the system falls back to the first available animation in the character prompt file.

---

## Current Implementations

| Method | Folder | Main File | Description |
|---|---|---|---|
| Baseline | `baseline/` | `baseline/main.py` | Single-agent beat-based storytelling |
| Director Agent | `director_agent/` | `director_agent/main.py` | Director handles interruptions and story steering |

---

````markdown
---

# Time-Constrained Director-Agent

The time-constrained director-agent adds a time limit to the normal director-agent. It tracks remaining time and changes pacing:

```text
normal   = continue normally
hurry    = move faster
critical = compress beats
final    = end the story immediately
````

## Files

```text
time_control.py
director_agent/time_director_core.py
director_agent/time_main.py
director_agent/time_auto_main.py
director_agent/time_runner.py
```

## Run Interactive Version

Use this to test manually by typing user inputs.

```bash
python director_agent/time_main.py \
  --character character_prompts.olaf \
  --scenario scenarios.olaf_retells_red_riding_hood_derail \
  --time-limit 5
```

Stop with:

```text
quit
```

## Run One Automated Scripted Version

Uses the `user_inputs` from the scenario file.

```bash
python director_agent/time_auto_main.py \
  --character character_prompts.olaf \
  --scenario scenarios.olaf_retells_red_riding_hood_derail \
  --time-limit 5 \
  --run-id 1
```

## Run Multiple Automated Evaluation Runs

```bash
python director_agent/time_runner.py \
  --character character_prompts.olaf \
  --scenario scenarios.olaf_retells_red_riding_hood_derail \
  --time-limit 5 \
  --runs 5
```

## Run Different Time Budgets

```bash
python director_agent/time_runner.py \
  --character character_prompts.olaf \
  --scenario scenarios.olaf_retells_red_riding_hood_derail \
  --time-limit 5 \
  --runs 5
```

```bash
python director_agent/time_runner.py \
  --character character_prompts.olaf \
  --scenario scenarios.olaf_retells_red_riding_hood_derail \
  --time-limit 10 \
  --runs 5
```

## Output Location

Interactive output is saved in:

```text
director_agent/outputs/
```

Automated evaluation outputs are saved in:

```text
outputs/time_constrained_director_agent/<scenario_name>/<time_limit>min/
```

Example:

```text
outputs/time_constrained_director_agent/olaf_retells_red_riding_hood_derail/5.0min/run_1.json
outputs/time_constrained_director_agent/olaf_retells_red_riding_hood_derail/5.0min/run_2.json
outputs/time_constrained_director_agent/olaf_retells_red_riding_hood_derail/5.0min/run_3.json
outputs/time_constrained_director_agent/olaf_retells_red_riding_hood_derail/5.0min/run_4.json
outputs/time_constrained_director_agent/olaf_retells_red_riding_hood_derail/5.0min/run_5.json
```

## Output Contains

Each JSON transcript stores:

```text
method
character
scenario
run_id
turn_index
time_limit_minutes
beat
user_input
temporal_state
director_decision
actor_output
```

The important new field is:

```text
temporal_state
```

It shows elapsed time, remaining time, story progress, and pacing mode for each turn.

```
```
