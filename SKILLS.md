# Development guide

Grid Up: early warning for anomalies inside LV/MV panels and cells (temperature, current, humidity,
partial discharge, arc). On-premise, no public cloud.

## Components and ownership

| Path | Concern | Owner |
|---|---|---|
| `ai/` | anomaly detection, risk scoring, inference contract | Duygu |
| `src/grid_up_anomaly_detection/` | root Poetry scaffold | Yusuf |

Backend/monitoring, frontend, SCADA/Modbus and hardware docs get their own top-level folders
when they have real content.

## AI component

```bash
cd ai
poetry install --all-extras
poetry run pytest -q
poetry run ruff check .
```

* Python ≥ 3.11, Poetry, dependencies declared in `ai/pyproject.toml` only.
* Canonical runtime scoring path: `RiskEngine.update()` in `ai/src/gridup_ai/engine.py`.
  Do not add a second (stateless) risk engine; `RiskEngine.score()` is its batch form.
* Every threshold lives in `ai/configs/default.yaml` with a provenance tag
  (`[DOC]`, `[DATA]`, `[EXT]`, `[ASSUMPTION]`, `[DEMO]`, `[PLACEHOLDER]`).
  An electrical limit not backed by a supplied specification stays `[PLACEHOLDER]` and configurable.
  Never present one as authoritative.
* Design rules: physics/rules first, lightweight ML only as a capped supporting signal (ML alone never
  reaches CRITICAL); arc is a direct event, not an ML output; PD needs temporal context; missing sensors
  lower confidence instead of raising risk; no deep learning.
* The inference payload is a contract (`ai/docs/inference_contract.md`): add fields, never remove or
  retype them within `schema_version` 1.x.
* Generated data, models and reports (`ai/data/synthetic/`, `ai/models/`, `ai/reports/`) are
  reproducible from scripts and are never committed.

## Conventions

* Ruff, line length 120. Match the surrounding code; no style-only rewrites.
* Tests assert behaviour (detection, false alarms, degradation), not coverage numbers.
* Paths come from `gridup_ai.config`; no absolute or user-specific paths.

## Git workflow

* Personal working branches (e.g. `duygu`); never push to `main` directly. Merge via pull request.
* Small, coherent commits with conventional prefixes (`feat(ai):`, `fix(ai):`, `chore:`).

## Confidential material: do not commit

Hackathon material marked **Restricted / Hizmete Özel** stays out of Git. That includes the challenge
brief, ADM/GDZ and TEDAŞ documents, panel drawings, organizer-supplied vendor PDFs, the
"Hackathon Verileri" ZIP and the original Excel files. Keep local copies in the git-ignored `/data/`
folder (or point `GRIDUP_SUPPLIED_EXCEL` elsewhere). Test fixtures must be synthetic.
No `.env`, credentials or tokens in the repository.
