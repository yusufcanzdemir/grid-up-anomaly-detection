# gridup-ai — anomaly detection & risk engine

AI component of Grid Up. It turns per-module sensor readings (phase currents, lug/cabinet/room
temperature, humidity, optional partial discharge, TVOC-2 arc status) into a risk score, a status, a
suspected condition and human-readable reasons. CPU only, on-premise, no cloud calls.

* Output payload for backend/dashboard: [docs/inference_contract.md](docs/inference_contract.md)
* Modbus read maps + proposed SCADA output block: [docs/scada_mapping.md](docs/scada_mapping.md)

## Install & test

```bash
cd ai
poetry install --all-extras      # --all-extras adds the FastAPI prototype (needed by tests/test_service.py)
poetry run pytest -q
poetry run ruff check .
```

## How a risk score is produced

```
reading -> schema.validate -> features.build_features -> risk.evidence -> noisy-OR fusion -> risk 0-100
                                   ^                                            ^
                 per-module thermal baseline (baseline.py)       hard rule floors (arc, absolute temperature,
                 + Isolation Forest novelty (ml.py)              overload, condensation, sensor fault)
```

1. **Hard rules** work with no model at all. An arc trip is an event, never a model prediction.
2. **Physics baseline**: `T_lug − T_cabinet ≈ a·LPF_τ((I/Ir)²·R_cu(T)) + b`, fitted per module on
   commissioning data. The load-normalised heating index and phase asymmetry are the early-warning features.
3. **ML novelty**: Isolation Forest, weight-capped so ML alone never exceeds WATCH.
4. **Fusion + diagnosis**: noisy-OR across independent channels, then a signature table picks the
   suspected condition and recommended action.

Missing or faulty sensors lower `confidence` and raise at most a WATCH-level `SENSOR_FAULT`.
PD evidence uses rolling windows and a trend; a single PD sample is never enough.

Runtime entry point: `RiskEngine.update(reading)` (streaming). `RiskEngine.score(df)` is the batch form
of the same code path, used by training/evaluation.

## Pipeline (reproducible, fixed seed)

Generated files go to `data/synthetic/`, `models/`, `reports/` and are git-ignored.

```bash
poetry run python scripts/generate_synthetic.py   # scenario dataset + ground truth
poetry run python scripts/train.py                # per-module baselines + Isolation Forest
poetry run python scripts/evaluate.py             # scenario report + sample payloads
poetry run python scripts/diagnose_run.py loose_connection
poetry run python scripts/scale_test.py --modules 100
poetry run python scripts/audit_data.py           # only with the organizer workbook (GRIDUP_SUPPLIED_EXCEL)
```

Live demo (after the pipeline):

```bash
poetry run uvicorn gridup_ai.service.app:app --port 8000
poetry run python scripts/replay.py --scenario loose_connection --speed 600
```

## Module map

| file | role |
|---|---|
| `configs/default.yaml` | every threshold, tagged `[DOC]/[DATA]/[EXT]/[ASSUMPTION]/[DEMO]/[PLACEHOLDER]` |
| `schema.py` | canonical reading schema + validation |
| `physics.py` | dew point, absolute humidity, copper factor, first-order thermal filter |
| `baseline.py` | per-module thermal fit (commissioning) |
| `features.py` | heating index, residual z, asymmetry, trends, PD, sensor health |
| `risk.py` | evidence ramps, persistence, floors, fusion, status hysteresis, health, diagnosis |
| `reasons.py` | stable reason/condition codes and TR/EN messages |
| `ml.py` | Isolation Forest + occlusion attribution |
| `engine.py` | `RiskEngine`: batch & streaming inference, output contract |
| `modbus_maps.py` | MPR-53CS / TVOC-2 read maps, proposed SCADA block |
| `loaders.py` | reader for the organizer current workbook format (mA → A) |
| `simulator.py`, `evaluation.py` | synthetic scenarios with ground truth, scenario-level metrics |
| `observability.py` | one-line tick formatting |
| `service/` | FastAPI prototype with in-memory store (`api` extra) |
