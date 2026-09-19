# Inference contract v1.1 (frozen, additive)

One JSON object per module per inference. Produced by `RiskEngine.update()` / `POST /ingest`, and
also served by `GET /modules/{id}/latest`. Examples for all four states are generated (not committed)
by `scripts/evaluate.py` into `ai/reports/sample_outputs.json` → `examples.NORMAL|WATCH|WARNING|CRITICAL`.

**Stability rules for the backend/dashboard**

* `code` / `code_id` values (statuses, conditions, reasons) are **stable**; never parse `message`.
* Within `schema_version` 1.x fields may be **added**, never removed or retyped.
* Any numeric field may be `null` when the underlying sensor is absent — render "n/a", not 0.

## Top level

| Field | Type | Notes |
|---|---|---|
| `schema_version` | string | `"1.1"` — 1.1 added `sensor_summary.arc.detected_no_trip` and reason `ARC_DETECTED_NO_TRIP`; nothing was removed or retyped |
| `module_id` | string | monitored circuit (3 phases), e.g. `PANEL-03` |
| `panel_id`, `site_id` | string\|null | from the reading |
| `timestamp` | ISO-8601 UTC, `...Z` | timestamp of the reading, not of processing |
| `status` | enum | `NORMAL` \| `WATCH` \| `WARNING` \| `CRITICAL` |
| `status_code` | int | 0 \| 1 \| 2 \| 3 — use this for sorting/thresholding |
| `previous_status`, `status_changed` | enum, bool | for event/toast logic |
| `risk_score` | int 0–100 | **now**: how bad is it at this moment |
| `health_score` | int 0–100 | **accumulated condition**; falls fast, recovers slowly |
| `confidence` | float 0–1 | trust in the assessment (sensor completeness, baseline, ML) |
| `anomaly_score` | float 0–1 \| null | ML novelty severity only; `null` if ML unavailable |
| `suspected_condition` | object | see below |
| `reasons` | array | ordered, highest contribution first, max 6 |
| `hard_rules` | string[] | safety rules currently latched, e.g. `["ARC_TRIP"]` |
| `group_scores` | object | per-channel evidence 0–1: thermal, ventilation, electrical, environment, discharge, ml |
| `time_to_critical_h` | float \| null | linear extrapolation of the current trend, **not** a survival estimate |
| `recommended_action` | string (TR) | operator instruction for the suspected condition |
| `notify` | object | `{channels: [...], priority: high\|medium\|low\|none}` |
| `sensor_summary` | object | what the sensors reported, see below |
| `key_values` | object | headline numbers for the module card |
| `data_quality` | object | `{completeness, faulty_channels[], missing_channels[], ml_available, baseline_valid}` |

### Status bands

| Status | risk | Meaning | Notification |
|---|---|---|---|
| `NORMAL` | 0–29 | Behaviour matches the learned baseline | none |
| `WATCH` | 30–59 | Something is off; no action needed yet | dashboard |
| `WARNING` | 60–79 | Developing fault; plan an intervention | dashboard + SMS + SCADA |
| `CRITICAL` | 80–100 | Act now | dashboard + SMS + WhatsApp + SCADA |

Escalation is immediate; de-escalation needs 30 min below (band − 5) so the UI does not flap.
Environment-only and ML-only evidence cannot exceed `WATCH` by design.

### `suspected_condition`

```jsonc
{"code": "LOOSE_CONNECTION", "code_id": 1, "label": "Gevşek / oksitlenmiş bağlantı şüphesi",
 "confidence": 0.78, "affected_phase": "L2"}   // affected_phase only for phase-local conditions
```

Codes: `NONE`0 `LOOSE_CONNECTION`1 `VENTILATION_DEGRADATION`2 `OVERLOAD`3 `CONDENSATION_RISK`4
`INSULATION_DEGRADATION`5 `ARC_FLASH`6 `SENSOR_FAULT`7 `PROTECTION_UNAVAILABLE`8 `UNEXPLAINED_ANOMALY`9.

### `reasons[]`

```jsonc
{"code": "PHASE_ASYMMETRY", "code_id": 11, "group": "thermal", "source": "thermal_model",
 "kind": "evidence",            // "evidence" (learned/statistical) or "rule" (hard safety rule)
 "severity": 0.83,              // 0-1, how strong this single piece of evidence is
 "contribution": 0.46,          // 0-1, share of the final risk; contributions sum to <= 1
 "value": 1.71, "unit": "x",
 "message": "L2 fazı diğer fazlara göre 1.7 kat fazla ısınıyor (yük düzeltmeli)",
 "message_en": "L2 heats 1.7x more than the other phases (load-corrected)"}
```

`source` values: `thermal_model`, `thermal_image`, `trend_analysis`, `temperature_sensor`,
`humidity_sensor`, `psychrometrics`, `energy_analyzer`, `hfct_pd`, `tvoc2_arc_guard`,
`isolation_forest`, `sensor_health`, `safety_rule`.

Reason codes: `CONNECTION_HEATING`10 `PHASE_ASYMMETRY`11 `LUG_RESIDUAL`12 `HEATING_TREND`13
`ABS_TEMPERATURE`14 `CABINET_HEATING`20 `THERMAL_OVERLOAD`30 `NEUTRAL_CURRENT`31 `HUMIDITY_HIGH`40
`CONDENSATION`41 `PD_ACTIVITY`50 `PD_TREND`51 `ML_ANOMALY`60 `ARC_TRIP`90 `ARC_SYSTEM_ERROR`91
`ARC_LIGHT_WARNING`92 `ABS_TEMP_CRITICAL`93 `OVERLOAD_RULE`94 `SENSOR_FAULT`95 `CONDENSATION_RULE`96
`ARC_DETECTED_NO_TRIP`97.

When a hard rule dominates the score, that rule carries the whole contribution and the statistical
reasons are still listed with `contribution: 0` for context.

### `sensor_summary`

Five groups, each with a `status` of `ok` | `partial` | `degraded` | `not_installed` (`arc` uses
`ok` | `error`):

```jsonc
{"current":           {"l1_a": 261.3, "l2_a": 243.1, "l3_a": 279.4, "n_a": 31.2, "thd_pct": 9.4,
                       "max_pu": 0.70, "status": "ok"},
 "temperature":       {"l1_c": 52.1, "l2_c": 71.8, "l3_c": 52.9, "internal_c": 34.2,
                       "ambient_c": 24.6, "max_c": 71.8, "status": "ok"},
 "humidity":          {"rh_pct": 31.4, "dew_point_c": 6.2, "dew_margin_c": 18.4, "status": "ok"},
 "partial_discharge": {"rate_per_min": null, "peak_mv": null, "status": "not_installed"},
 "arc":               {"trip_active": false, "detected_no_trip": false, "system_error": false,
                       "light_warning": false, "status": "ok"}}
```

### `data_quality` and confidence

`completeness` is the fraction of installed channels present in this sample. `faulty_channels` lists
channels detected as stuck or dropped; `missing_channels` lists channels with no value in this sample.
`confidence` = `(0.5 + 0.5·completeness)` × `0.80 if baseline invalid` × `0.95 if ML unavailable` ×
`max(0.6, 1 − 0.1·n_faulty)`.

**A failed sensor lowers `confidence`, it never raises `risk_score`** — it does raise a `WATCH`-level
`SENSOR_FAULT` because a blind monitor is an operations problem.

## Notes for the dashboard

* Sort module lists by `status_code` then `risk_score`.
* The module card needs only `status`, `risk_score`, `health_score`, `suspected_condition.label`,
  `reasons[0].message` and `key_values`.
* `time_to_critical_h` is an explicit trend extrapolation — label it "tahmini" (estimated), never
  present it as a guaranteed remaining life.
