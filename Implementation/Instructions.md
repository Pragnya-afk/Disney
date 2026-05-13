```markdown
# Running the Systems

## 1. Baseline Interactive (ie no pre defined inputs)

Interactive mode lets you type your own user inputs.

```bash
python baseline/main.py \
  --character character_prompts.olaf \
  --scenario scenarios.olaf_retells_red_riding_hood_medium
```
 -> saves in  baseline/outputs/
### Output

---

## 2. Director-Agent Interactive

Interactive mode lets you type your own user inputs.

```bash
python director_agent/main.py \
  --character character_prompts.olaf \
  --scenario scenarios.olaf_retells_red_riding_hood_medium
```
 -> output in director_agent/outputs/
---

## 3. Baseline Automatic

Automatic mode uses the predefined `user_inputs` from the scenario file.

```bash
python baseline/auto_main.py \
  --character character_prompts.olaf \
  --scenario scenarios.olaf_retells_red_riding_hood_medium \
  --run-id 1 ## output file gets name 1 
  --runs 5 ## multiple runs 
```
-> output single: outputs/baseline/<scenario_name>/run_<id>.json
-> output multi-run : 
    `run_1.json`
    * `run_2.json`
    * ...
    * `run_5.json`

    in the corresponding `outputs/` directory

---

## 4. Director-Agent Automatic

Automatic mode uses the predefined `user_inputs` from the scenario file.

```bash
python director_agent/auto_main.py \
  --character character_prompts.olaf \
  --scenario scenarios.olaf_retells_red_riding_hood_medium \
  --run-id 1
   --runs 5 ## multiple runs 
```
-> output single: outputs/director_agent/<scenario_name>/run_<id>.json
-> output multiple: 
    `run_1.json`
    * `run_2.json`
    * ...
    * `run_5.json`

    in the corresponding `outputs/` directory

### Note

If you rerun the same command with the same run id, that file is overwritten.

---

# Evaluation

## Evaluate One Pair of Output Files

```bash
python evaluation/evaluation_agent.py \
  --story-a outputs/baseline/olaf_retells_red_riding_hood_medium/run_1.json \
  --story-b outputs/director_agent/olaf_retells_red_riding_hood_medium/run_1.json \
  --character-module character_prompts.olaf \
  --scenario-module scenarios.olaf_retells_red_riding_hood_medium \
  --out-dir evaluation/results/olaf_retells_red_riding_hood_medium \
  --ab-ba
```

-> Output: evaluation/results/<scenario_name>/

**Note:** `--scenario-module` is required because story topic and beats are defined in the scenario module, not the character module.

---

## Extract Only Character Outputs

```bash
python evaluation/extract_character_outputs.py \
  --baseline outputs/baseline/olaf_retells_red_riding_hood_medium/run_1.json \
  --director outputs/director_agent/olaf_retells_red_riding_hood_medium/run_1.json \
  --out evaluation/results/olaf_retells_red_riding_hood_medium/run_1_character_outputs.txt
```
-> output : evaluation/results/olaf_retells_red_riding_hood_medium/run_1_character_outputs.txt


## Summarize Results Across Multiple Evaluations

```bash
python evaluation/summarize_results.py
```

This is used after evaluating multiple run pairs.

Typical uses:

* average single-story scores across runs
* count category winners across runs
* compute final majority winners for AB evaluation categories

---
## Extract Character Outputs into One Readable File

If you want a plain text file that contains only the character responses from one baseline run and one director-agent run, use:

```bash
python evaluation/extract_character_outputs.py \
  --baseline outputs/baseline/olaf_retells_red_riding_hood_medium/run_1.json \
  --director outputs/director_agent/olaf_retells_red_riding_hood_medium/run_1.json \
  --out evaluation/results/olaf_retells_red_riding_hood_medium/run_1_character_outputs.txt








# Typical Workflow

## Quick Single Test

### 1. Run baseline

```bash
python baseline/auto_main.py \
  --character character_prompts.olaf \
  --scenario scenarios.olaf_retells_red_riding_hood_medium \
  --run-id 1
```

### 2. Run director-agent

```bash
python director_agent/auto_main.py \
  --character character_prompts.olaf \
  --scenario scenarios.olaf_retells_red_riding_hood_medium \
  --run-id 1
```

### 3. Evaluate

```bash
python evaluation/evaluation_agent.py \
  --story-a outputs/baseline/olaf_retells_red_riding_hood_medium/run_1.json \
  --story-b outputs/director_agent/olaf_retells_red_riding_hood_medium/run_1.json \
  --character-module character_prompts.olaf \
  --scenario-module scenarios.olaf_retells_red_riding_hood_medium \
  --out-dir evaluation/results/olaf_retells_red_riding_hood_medium \
  --ab-ba
```

---

## Full 5-Run Experiment

### 1. Generate 5 baseline runs

```bash
python baseline/runner.py \
  --character character_prompts.olaf \
  --scenario scenarios.olaf_retells_red_riding_hood_medium \
  --runs 5
```

### 2. Generate 5 director-agent runs

```bash
python director_agent/runner.py \
  --character character_prompts.olaf \
  --scenario scenarios.olaf_retells_red_riding_hood_medium \
  --runs 5
```

### 3. Evaluate each matching pair

For example:

* baseline run 1 vs director run 1
* baseline run 2 vs director run 2
* ...
* baseline run 5 vs director run 5

### 4. Summarize all results

```bash
python evaluation/summarize_results.py
```

---

# Important Notes

## Interactive vs Automatic

* `main.py` = interactive, you type the inputs
* `auto_main.py` = non-interactive, uses scenario `user_inputs`

## Scenario choice

If you do not want predefined user inputs, use `main.py`, not `auto_main.py`.

## Recommended scenarios

* `scenarios.olaf_anna_courtyard` for simple sanity checks
* `scenarios.olaf_retells_red_riding_hood_medium` for medium-complexity testing
* `scenarios.olaf_retells_red_riding_hood_derail` for disruptive interruption stress tests

```
```
