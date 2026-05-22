Outputs layout
=============

This folder stores generated transcripts and evaluation artifacts produced by the Implementation scripts.

Structure
---------
- `baseline/<scenario>/run_<id>.json` — automated baseline runs
- `baseline/<scenario>/interactive.json` — interactive baseline transcript

- `director_agent/<scenario>/run_<id>.json` — automated director-agent runs
- `director_agent/<scenario>/interactive.json` — interactive director transcripts

- `target_duration_director_agent/<scenario>/<time>min/run_<id>.json` — automated target-duration director runs
- `target_duration_director_agent/<scenario>/<time>min/interactive.json` — interactive target-duration director run

- `target_duration_baseline/<scenario>/<time>min/` — analogous to target-duration director for baseline
- `time_constrained_director_agent/<scenario>/<time>min/run_<id>.json` — time-constrained experiments
- `codi/<scenario>/run_<id>.json` — CoDi-generated outputs

Notes
-----
- Interactive runs use `interactive.json` to distinguish them from batch `run_<id>.json` outputs.
- Keep generated outputs under `Implementation/outputs/` to avoid mixing artifacts with source code.
