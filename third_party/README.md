# Third-party code

Vendored for the baseline comparisons; kept unchanged apart from the local edits noted below.

| Folder | Upstream | License | Local changes |
|---|---|---|---|
| `CoDi-main/CoDi-main/` | CoDi (Honggu Kim, 2025) | MIT (`LICENSE`) | `generation.py`, `score_evaluation.py`, `scripts/evaluate.sh`, `data/example.jsonl` edited for the thesis scenarios; `outputs/` holds the CoDi runs used in the thesis |
| `AIDungeon-develop/` | https://github.com/AIDungeon/AIDungeon | MIT (`LICENSE`) | none; reference only, not imported by thesis code |

CoDi's own dependencies are listed in `CoDi-main/CoDi-main/requirements.txt`; install them in a separate venv.
