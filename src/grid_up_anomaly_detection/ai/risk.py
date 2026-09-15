"""Risk engine: evidence severities -> persistence -> noisy-OR fusion -> hard-rule floors -> status.

risk_fused = 1 - prod_g (1 - w_g * E_g)          E_g = max_k in g  mean_{confirm window}(sev_k)
risk       = 100 * max(risk_fused, max(hard-rule floors))
contribution_g = -ln(1 - w_g E_g) / sum_j -ln(1 - w_j E_j)   (exact additive split of -ln(1-risk_fused))
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .reasons import SIGNATURES

STATUSES = ["NORMAL", "WATCH", "WARNING", "CRITICAL"]
PANEL_RULES = ["ARC_TRIP", "ABS_TEMP_CRITICAL", "OVERLOAD_RULE", "ARC_SYSTEM_ERROR", "CONDENSATION_RULE"]


def ramp(x: pd.Series, lo: float, hi: float) -> pd.Series:
    return ((x - lo) / (hi - lo)).clip(0, 1).fillna(0.0)


def evidence(F: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (raw severities, persistence-filtered severities), one column per evidence code."""
    raw, eff = {}, {}
    for code, e in cfg["evidence"].items():
        x = F[e["col"]] if e["col"] in F else pd.Series(np.nan, index=F.index)
        s = ramp(x.astype(float), e["lo"], e["hi"])
        raw[code] = s
        eff[code] = s.rolling(f"{e['confirm_min']}min", min_periods=1).mean()
    return pd.DataFrame(raw, index=F.index), pd.DataFrame(eff, index=F.index)


def rule_floors(F: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    r = cfg["rules"]
    fl = pd.DataFrame(index=F.index)
    latch = F["arc_trip_new"].rolling(f"{r['arc_latch_min']}min", min_periods=1).max() > 0
    fl["ARC_TRIP"] = np.where((F["arc_trip_active"] > 0) | latch, r["arc_trip_floor"], 0.0)
    fl["ARC_SYSTEM_ERROR"] = np.where(F["arc_system_error"] > 0, r["arc_system_error_floor"], 0.0)
    fl["ARC_LIGHT_WARNING"] = np.where(F["arc_light_warning"] > 0, r["arc_light_warning_floor"], 0.0)
    tmin5 = F["temp_max_f"].rolling("5min", min_periods=1).min()
    fl["ABS_TEMP_CRITICAL"] = np.where(tmin5 >= r["abs_temp_critical_c"], r["abs_temp_critical_floor"], 0.0)
    # sustained, not transient: cold-load pickup after a restoration must not page anyone
    th = F["theta"].fillna(0).rolling(f"{r['theta_hold_min']}min", min_periods=5).min()
    fl["OVERLOAD_RULE"] = np.select([th >= r["theta_critical"], th >= r["theta_warning"]],
                                    [r["theta_critical_floor"], r["theta_warning_floor"]], 0.0)
    dew_hold = F["dew_margin_c"].rolling(f"{r['condensation_hold_min']}min", min_periods=5).max()
    fl["CONDENSATION_RULE"] = np.where(dew_hold <= r["condensation_margin_c"], r["condensation_floor"], 0.0)
    fault_cols = [c for c in F if c.startswith("fault_")]
    fl["SENSOR_FAULT"] = np.where(F[fault_cols].any(axis=1), r["sensor_fault_floor"], 0.0)
    return fl


def fuse(eff: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    groups: dict[str, list[str]] = {}
    for code, e in cfg["evidence"].items():
        groups.setdefault(e["group"], []).append(code)
    G = pd.DataFrame({g: eff[codes].max(axis=1) for g, codes in groups.items()}, index=eff.index)
    w = pd.Series(cfg["group_weights"])
    G["risk_fused"] = 1 - (1 - G[list(groups)] * w[list(groups)]).prod(axis=1)
    return G


def status_with_hysteresis(ts: pd.DatetimeIndex, risk: np.ndarray, cfg: dict,
                           state: dict | None = None) -> tuple[np.ndarray, dict]:
    """Escalate immediately; de-escalate only after risk stays below (band - margin) for hold_min."""
    b = cfg["status"]["bands"]
    lower = [0, b["WATCH"], b["WARNING"], b["CRITICAL"]]
    margin, hold = cfg["status"]["deescalate_margin"], pd.Timedelta(minutes=cfg["status"]["deescalate_hold_min"])
    st = dict(state or {"level": 0, "below_since": None})
    out = np.empty(len(risk), dtype=int)
    for i, (t, r) in enumerate(zip(ts, risk)):
        lvl = int(np.searchsorted(lower, r, side="right") - 1)
        if lvl >= st["level"]:
            st["level"], st["below_since"] = lvl, None
        elif r < lower[st["level"]] - margin:
            st["below_since"] = st["below_since"] or t
            if t - st["below_since"] >= hold:
                st["level"], st["below_since"] = lvl, None
        else:
            st["below_since"] = None
        out[i] = st["level"]
    return out, st


def health_index(ts: pd.DatetimeIndex, r_panel: np.ndarray, cfg: dict) -> np.ndarray:
    """Fast attack (1 h), slow release (health_tau_h): drops quickly on damage, recovers only slowly."""
    t = ((ts - ts[0]).total_seconds() / 60.0).to_numpy()
    tau_up, tau_down = 60.0, cfg["status"]["health_tau_h"] * 60.0
    y = np.empty_like(r_panel)
    s = r_panel[0]
    for i in range(len(r_panel)):
        dt = t[i] - t[i - 1] if i else 0.0
        tau = tau_up if r_panel[i] > s else tau_down
        s += (1 - np.exp(-dt / tau)) * (r_panel[i] - s)
        y[i] = s
    return np.round(100 * (1 - y)).astype(int)


def diagnose(eff: pd.DataFrame, floors: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    scores = pd.DataFrame({c: sum(w * eff[k] for k, w in sig.items() if k in eff) for c, sig in SIGNATURES.items()},
                          index=eff.index)
    scores["OVERLOAD"] += floors["OVERLOAD_RULE"]
    scores["CONDENSATION_RISK"] += floors["CONDENSATION_RULE"]
    pos = scores.clip(lower=0)
    top = pos.idxmax(axis=1)
    best = pos.max(axis=1)
    conf = (best / pos.sum(axis=1).replace(0, np.nan)).fillna(0)
    cond = top.where(best >= 0.15, "NONE")
    cond = cond.where(~((cond == "NONE") & (floors["SENSOR_FAULT"] > 0)), "SENSOR_FAULT")
    cond = cond.where(floors["ARC_SYSTEM_ERROR"] == 0, "PROTECTION_UNAVAILABLE")
    cond = cond.where(floors["ARC_TRIP"] == 0, "ARC_FLASH")
    conf = conf.where(~cond.isin(["ARC_FLASH", "PROTECTION_UNAVAILABLE", "SENSOR_FAULT"]), 1.0)
    return cond, conf.round(2)


def score_frame(F: pd.DataFrame, cfg: dict, ml_sev: np.ndarray | None = None) -> pd.DataFrame:
    """Vectorised scoring of a feature frame (one module). Adds evidence, groups, risk, status, health."""
    F = F.copy()
    F["ml_sev"] = ml_sev if ml_sev is not None else np.nan
    raw, eff = evidence(F, cfg)
    floors = rule_floors(F, cfg)
    G = fuse(eff, cfg)
    floor_max = floors.max(axis=1)
    risk = np.round(100 * np.maximum(G["risk_fused"], floor_max)).astype(int)
    status, _ = status_with_hysteresis(F.index, risk.to_numpy(), cfg)
    r_panel = np.maximum(G["risk_fused"], floors[PANEL_RULES].max(axis=1)).to_numpy()
    cond, conf = diagnose(eff, floors)
    out = pd.concat([F, raw.add_prefix("sev_"), eff.add_prefix("eff_"), floors.add_prefix("floor_"),
                     G.add_prefix("grp_").rename(columns={"grp_risk_fused": "risk_fused"})], axis=1)
    out["risk"] = risk
    out["status_code"] = status
    out["status"] = np.array(STATUSES)[status]
    out["health"] = health_index(F.index, r_panel, cfg)
    out["condition"] = cond
    out["condition_confidence"] = conf
    return out
