"""Inference engine: canonical readings -> scored frame -> JSON output contract.

Batch:     RiskEngine.score(df_module)        (training / evaluation / replay)
Streaming: RiskEngine.update(reading_dict)    (one module, one timestamp -> output dict)
Both use exactly the same feature and risk code paths.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from . import risk as risk_mod
from .baseline import ModuleBaseline
from .features import MONITORED_CHANNELS, build_features
from .ml import MLDetector
from .reasons import CONDITION_CODES, CONDITION_LABELS, REASON_CODES, REASON_SOURCES, REASONS, RECOMMENDED_ACTIONS
from .schema import CANONICAL_COLUMNS, validate

SCHEMA_VERSION = "1.0"
BUFFER_HOURS = 26
NOTIFY = {
    "CRITICAL": {"channels": ["dashboard", "sms", "whatsapp", "scada"], "priority": "high"},
    "WARNING": {"channels": ["dashboard", "sms", "scada"], "priority": "medium"},
    "WATCH": {"channels": ["dashboard"], "priority": "low"},
    "NORMAL": {"channels": [], "priority": "none"},
}


class RiskEngine:
    def __init__(self, cfg: dict, baselines: dict[str, ModuleBaseline], ml: MLDetector | None = None):
        self.cfg = cfg
        self.baselines = baselines
        self.ml = ml
        self.buffers: dict[str, pd.DataFrame] = {}
        self.state: dict[str, dict] = {}
        self.groups = {c: e["group"] for c, e in cfg["evidence"].items()}

    # ---------------- batch ----------------
    def score(self, df: pd.DataFrame) -> pd.DataFrame:
        module_id = str(df["module_id"].iloc[0])
        bl = self.baselines.get(module_id)
        rated = bl.rated_a if bl else float(df.attrs.get("rated_a", self.cfg["panel"]["feeder_rated_a"]))
        clean = validate(df, self.cfg, rated)
        clean.attrs.update(df.attrs)
        F = build_features(clean, bl, self.cfg)
        ml_sev = None
        if self.ml is not None:
            try:
                ml_sev = self.ml.severity(F)
            except Exception:
                ml_sev = None
        scored = risk_mod.score_frame(F, self.cfg, ml_sev)
        scored["ml_available"] = ml_sev is not None
        # keep identity with the frame: batch scoring has no streaming buffer to read it back from
        scored.attrs.update(module_id=module_id, panel_id=_first(clean, "panel_id"),
                            site_id=_first(clean, "site_id"), profile=_first(clean, "profile"))
        return scored

    # ---------------- streaming ----------------
    def update(self, reading: dict[str, Any]) -> dict[str, Any]:
        mid = str(reading["module_id"])
        row = pd.DataFrame([{c: reading.get(c) for c in CANONICAL_COLUMNS}])
        buf = pd.concat([self.buffers.get(mid, pd.DataFrame(columns=CANONICAL_COLUMNS)), row], ignore_index=True)
        buf["timestamp"] = pd.to_datetime(buf["timestamp"], utc=True)
        buf = buf[buf["timestamp"] >= buf["timestamp"].iloc[-1] - pd.Timedelta(hours=BUFFER_HOURS)]
        self.buffers[mid] = buf.reset_index(drop=True)
        scored = self.score(self.buffers[mid])
        # status hysteresis must be continuous across calls -> recompute only the last point with kept state
        st, self.state[mid] = risk_mod.status_with_hysteresis(
            scored.index[-1:], scored["risk"].to_numpy()[-1:], self.cfg, self.state.get(mid))
        scored.iloc[-1, scored.columns.get_loc("status_code")] = st[0]
        scored.iloc[-1, scored.columns.get_loc("status")] = risk_mod.STATUSES[st[0]]
        return self.output(scored, mid)

    # ---------------- output contract ----------------
    def output(self, scored: pd.DataFrame, module_id: str, i: int = -1) -> dict[str, Any]:
        cfg = self.cfg
        row = scored.iloc[i]
        prev = scored.iloc[i - 1] if len(scored) > 1 else row
        w = cfg["group_weights"]
        groups = {g: float(row.get(f"grp_{g}", 0.0)) for g in w}
        # exact additive split of -ln(1 - risk_fused) over groups, then over evidences inside a group
        gl = {g: -np.log(max(1e-9, 1 - w[g] * v)) for g, v in groups.items()}
        tot = sum(gl.values()) or 1.0
        floors = {c[6:]: float(row[c]) for c in scored.columns if c.startswith("floor_") and row[c] > 0}
        floor_max = max(floors.values(), default=0.0)
        fused = float(row["risk_fused"])
        rule_driven = floor_max >= fused

        reasons = []
        for code, g in self.groups.items():
            sev = float(row.get(f"eff_{code}", 0.0))
            if sev < 0.05 or groups.get(g, 0) <= 0:
                continue
            share = sev / max(groups[g], 1e-9)
            contrib = (gl[g] / tot) * min(1.0, share) * (0.0 if rule_driven else 1.0)
            reasons.append(self._reason(code, g, sev, contrib, row))
        for code, fl in floors.items():
            contrib = (fl / max(floor_max, 1e-9)) if rule_driven else 0.0
            reasons.append(self._reason(code, "rule", min(1.0, fl), contrib, row, is_rule=True))
        reasons.sort(key=lambda r: (-r["contribution"], -r["severity"]))

        cond = str(row["condition"])
        ttc = self._time_to_critical(row)
        status = str(row["status"])
        dq_faults = [c[6:] for c in scored.columns if c.startswith("fault_") and bool(row[c])]
        missing = [c for c in MONITORED_CHANNELS if c in scored and pd.isna(row.get(c, np.nan))]
        return {
            "schema_version": SCHEMA_VERSION,
            "module_id": module_id,
            "panel_id": scored.attrs.get("panel_id"),
            "site_id": scored.attrs.get("site_id"),
            "timestamp": row.name.isoformat().replace("+00:00", "Z"),
            "status": status,
            "status_code": int(row["status_code"]),
            "previous_status": str(prev["status"]),
            "status_changed": bool(prev["status"] != row["status"]),
            "risk_score": int(row["risk"]),
            "health_score": int(row["health"]),
            "anomaly_score": round(float(row.get("ml_sev", np.nan)), 3) if not pd.isna(row.get("ml_sev", np.nan)) else None,
            "confidence": _confidence(float(row.get("completeness", 0.0)), dq_faults,
                                      bool(row.get("baseline_valid", False)), bool(row.get("ml_available", False))),
            "sensor_summary": _sensor_summary(row, dq_faults),
            "suspected_condition": {
                "code": cond, "code_id": CONDITION_CODES.get(cond, 0), "label": CONDITION_LABELS.get(cond, cond),
                "confidence": float(row["condition_confidence"]),
                "affected_phase": (str(row["hot_phase"]) if isinstance(row.get("hot_phase"), str) else None)
                if cond in ("LOOSE_CONNECTION",) else None,
            },
            "reasons": reasons[:6],
            "hard_rules": sorted(floors),
            "group_scores": {g: round(v, 3) for g, v in groups.items()},
            "time_to_critical_h": ttc,
            "recommended_action": RECOMMENDED_ACTIONS.get(cond, RECOMMENDED_ACTIONS["NONE"]),
            "notify": NOTIFY[status],
            "key_values": {
                "temp_max_c": _f(row.get("temp_max_f")), "temp_internal_c": _f(row.get("temp_internal_c")),
                "current_max_pu": _f(row.get("current_max_pu")), "humidity_pct": _f(row.get("rh")),
                "dew_margin_c": _f(row.get("dew_margin_c")), "pd_rate_per_min": _f(row.get("pd_rate")),
                "thermal_image": _f(row.get("theta")), "heat_index_max": _f(row.get("heat_index_max")),
                "hot_phase": row.get("hot_phase") if isinstance(row.get("hot_phase"), str) else None,
            },
            "data_quality": {
                "completeness": round(float(row.get("completeness", 0)), 3),
                "faulty_channels": dq_faults, "missing_channels": missing,
                "ml_available": bool(row.get("ml_available", False)),
                "baseline_valid": bool(row.get("baseline_valid", False)),
            },
        }

    def _reason(self, code: str, group: str, sev: float, contrib: float, row: pd.Series, is_rule: bool = False) -> dict:
        tr, en = REASONS.get(code, (0, code, code))[1:]
        col = self.cfg["evidence"].get(code, {}).get("col")
        val = float(row[col]) if col and col in row and not pd.isna(row[col]) else float("nan")
        phase = row.get("hot_phase") if isinstance(row.get("hot_phase"), str) else "?"
        fmt = dict(value=val, pct=val * 100 if code in ("THERMAL_OVERLOAD", "NEUTRAL_CURRENT") else val,
                   phase=phase, channels=", ".join(c[6:] for c in row.index if c.startswith("fault_") and row[c]))
        return {
            "code": code, "code_id": REASON_CODES.get(code, 0), "group": group,
            "source": REASON_SOURCES.get(code, group), "kind": "rule" if is_rule else "evidence",
            "severity": round(sev, 3), "contribution": round(contrib, 3),
            "value": None if np.isnan(val) else round(val, 2), "unit": _UNITS.get(code, ""),
            "message": _safe_format(tr, fmt), "message_en": _safe_format(en, fmt),
        }

    def _time_to_critical(self, row: pd.Series) -> float | None:
        slope = row.get("heat_index_slope")
        hi_now = row.get("heat_index_max")
        crit = self.cfg["evidence"]["CONNECTION_HEATING"]["hi"]
        if pd.isna(slope) or pd.isna(hi_now) or slope <= 0.02 or hi_now >= crit:
            return None
        return round(min((crit - hi_now) / slope * 24.0, 720.0), 1)


_UNITS = {"CONNECTION_HEATING": "x", "PHASE_ASYMMETRY": "x", "LUG_RESIDUAL": "sigma", "HEATING_TREND": "x/day",
          "ABS_TEMPERATURE": "degC", "CABINET_HEATING": "x", "THERMAL_OVERLOAD": "pu", "NEUTRAL_CURRENT": "pu",
          "HUMIDITY_HIGH": "%RH", "CONDENSATION": "degC", "PD_ACTIVITY": "sigma", "PD_TREND": "log/day"}


def _confidence(completeness: float, faulty: list[str], baseline_valid: bool, ml_available: bool) -> float:
    """How much the operator should trust this assessment (never a substitute for risk).

    Missing/failed sensors and an unfitted baseline lower confidence; they never raise risk.
    """
    conf = 0.5 + 0.5 * completeness
    if not baseline_valid:
        conf *= 0.80          # rules-only mode still works, but the early-warning layer is blind
    if not ml_available:
        conf *= 0.95
    conf *= max(0.6, 1.0 - 0.1 * len(faulty))
    return round(min(1.0, max(0.0, conf)), 2)


def _group_status(values: list, faulty: list[str], channels: list[str]) -> str:
    if any(c in faulty for c in channels):
        return "degraded"
    if all(v is None for v in values):
        return "not_installed"
    if any(v is None for v in values):
        return "partial"
    return "ok"


def _sensor_summary(row: pd.Series, faulty: list[str]) -> dict[str, Any]:
    """Per-subsystem view of what the sensors actually reported at this timestamp."""
    def raw(name: str) -> float | None:
        return _f(row.get(f"raw_{name}"))

    cur = [raw(f"current_{p}_a") for p in ("l1", "l2", "l3")]
    temps = [raw(f"temp_{p}_c") for p in ("l1", "l2", "l3")]
    pd_vals = [raw("pd_count_per_min"), raw("pd_peak_mv")]
    return {
        "current": {"l1_a": cur[0], "l2_a": cur[1], "l3_a": cur[2], "n_a": raw("current_n_a"),
                    "thd_pct": raw("current_thd_pct"), "max_pu": _f(row.get("current_max_pu")),
                    "status": _group_status(cur, faulty, [f"current_{p}_a" for p in ("l1", "l2", "l3")])},
        "temperature": {"l1_c": temps[0], "l2_c": temps[1], "l3_c": temps[2],
                        "internal_c": raw("temp_internal_c"), "ambient_c": raw("temp_ambient_c"),
                        "max_c": _f(row.get("temp_max_f")),
                        "status": _group_status(temps, faulty, [f"temp_{p}_c" for p in ("l1", "l2", "l3")])},
        "humidity": {"rh_pct": raw("humidity_internal_pct"), "dew_point_c": _f(row.get("dew_point_c")),
                     "dew_margin_c": _f(row.get("dew_margin_c")),
                     "status": _group_status([raw("humidity_internal_pct")], faulty, ["humidity_internal_pct"])},
        "partial_discharge": {"rate_per_min": _f(row.get("pd_rate")), "peak_mv": raw("pd_peak_mv"),
                              "status": _group_status(pd_vals, faulty, ["pd_count_per_min"])},
        "arc": {"trip_active": bool(row.get("arc_trip_active", 0)),
                "system_error": bool(row.get("arc_system_error", 0)),
                "light_warning": bool(row.get("arc_light_warning", 0)),
                "status": "error" if bool(row.get("arc_system_error", 0)) else "ok"},
    }


def _first(df: pd.DataFrame, col: str):
    v = df[col].dropna()
    return None if v.empty else str(v.iloc[0])


def _f(v) -> float | None:
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), 2)


def _safe_format(tpl: str, fmt: dict) -> str:
    try:
        return tpl.format(**fmt)
    except (KeyError, ValueError):
        return tpl
