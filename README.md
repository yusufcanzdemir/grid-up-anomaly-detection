# Grid Up — Anomaly Detection

Pano ve hücrelerde oluşabilecek anomalileri erken aşamada tespit etmek ve ilgili ekipleri kritik durumlar oluşmadan önce bilgilendirmek amacıyla geliştirilen izleme ve erken uyarı sistemi.

## Proje

Sistem; sıcaklık, akım, nem ve benzeri saha verilerini birlikte değerlendirerek normal çalışma koşullarından sapmaları tespit etmeyi ve olası arıza riskleri için erken uyarı üretmeyi hedefler.

## Temel Özellikler

* Sensör verilerinin izlenmesi
* Anomali ve risk tespiti
* Merkezi monitoring
* Alarm ve bildirim mekanizması
* SCADA / Modbus entegrasyonu
* On-premise çalışma
* Ölçeklenebilir sistem mimarisi

## Mimari

```
saha sensörleri / Modbus (MPR-53CS, TVOC-2) -> kanonik okuma -> AI risk motoru -> JSON çıktı sözleşmesi
                                                                   |                   |
                                                         kural + fizik tabanlı      backend / dashboard,
                                                         model + sınırlı ML         alarm, SCADA bloğu
```

> **Not:** `mqtt_to_db.py` ve ilgili MQTT hatları, yapay zeka (RiskEngine) motorundan tamamen bağımsızdır. Bu hat sadece saha sensörlerinden gelen ham veriyi (raw data) ileride kullanılmak üzere veritabanında (Data Lake) arşivlemek amacıyla bulunur. Anomali tespiti yapmaz.

Backend/monitoring, frontend, SCADA/Modbus entegrasyonu ve donanım dokümantasyonu içerik oluştukça kendi klasörlerine eklenecek. Geliştirme kuralları: [SKILLS.md](SKILLS.md).

## AI Risk Engine

AI component of Grid Up. It turns per-module sensor readings (phase currents, lug/cabinet/room temperature, humidity, optional partial discharge, TVOC-2 arc status) into a risk score, a status, a suspected condition and human-readable reasons. CPU only, on-premise, no cloud calls.

* Output payload for backend/dashboard: [src/grid_up_anomaly_detection/ai/docs/inference_contract.md](src/grid_up_anomaly_detection/ai/docs/inference_contract.md)
* Modbus read maps + proposed SCADA output block: [src/grid_up_anomaly_detection/ai/docs/scada_mapping.md](src/grid_up_anomaly_detection/ai/docs/scada_mapping.md)

### Install & test

```bash
poetry install --all-extras      # --all-extras adds the FastAPI prototype
poetry run pytest -q
poetry run ruff check .
```

### How a risk score is produced

```
reading -> schema.validate -> features.build_features -> risk.evidence -> noisy-OR fusion -> risk 0-100
                                   ^                                            ^
                 per-module thermal baseline (baseline.py)       hard rule floors (arc, absolute temperature,
                 + Isolation Forest novelty (ml.py)              overload, condensation, sensor fault)
```

1. **Hard rules** work with no model at all. An arc trip is an event, never a model prediction.
2. **Physics baseline**: `T_lug − T_cabinet ≈ a·LPF_τ((I/Ir)²·R_cu(T)) + b`, fitted per module on commissioning data. The load-normalised heating index and phase asymmetry are the early-warning features.
3. **ML novelty**: Isolation Forest, weight-capped so ML alone never exceeds WATCH.
4. **Fusion + diagnosis**: noisy-OR across independent channels, then a signature table picks the suspected condition and recommended action.

Missing or faulty sensors lower `confidence` and raise at most a WATCH-level `SENSOR_FAULT`.
PD evidence uses rolling windows and a trend; a single PD sample is never enough.

Runtime entry point: `RiskEngine.update(reading)` (streaming). `RiskEngine.score(df)` is the batch form of the same code path, used by training/evaluation.

### Pipeline (reproducible, fixed seed)

Generated files go to `data/synthetic/`, `models/`, `reports/` and are git-ignored.

```bash
poetry run python src/grid_up_anomaly_detection/ai/scripts/generate_synthetic.py   # scenario dataset + ground truth
poetry run python src/grid_up_anomaly_detection/ai/scripts/train.py                # per-module baselines + Isolation Forest
poetry run python src/grid_up_anomaly_detection/ai/scripts/evaluate.py             # scenario report + sample payloads
poetry run python src/grid_up_anomaly_detection/ai/scripts/diagnose_run.py loose_connection
poetry run python src/grid_up_anomaly_detection/ai/scripts/scale_test.py --modules 100
poetry run python src/grid_up_anomaly_detection/ai/scripts/audit_data.py           # only with the organizer workbook (GRIDUP_SUPPLIED_EXCEL)
```

Live demo (after the pipeline):

```bash
poetry run uvicorn grid_up_anomaly_detection.ai.service.app:app --port 8000
poetry run python src/grid_up_anomaly_detection/ai/scripts/replay.py --scenario loose_connection --speed 600
```
