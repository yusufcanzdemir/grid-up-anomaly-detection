"""Scenario-level evaluation.

Point-wise accuracy is meaningless here (labels are intervals and most data is normal), so we measure
what an operator cares about: did we catch it, how early, how often did we cry wolf, was the
explanation right.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

WARNING = 2
LEVELS = {"WATCH": 1, "WARNING": 2, "CRITICAL": 3}


def episodes(status_code: pd.Series, level: int = WARNING) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    on = (status_code >= level).to_numpy()
    idx = status_code.index
    out, start = [], None
    for i, v in enumerate(on):
        if v and start is None:
            start = idx[i]
        elif not v and start is not None:
            out.append((start, idx[i - 1]))
            start = None
    if start is not None:
        out.append((start, idx[-1]))
    return out


def first_time_at(status_code: pd.Series, level: int) -> pd.Timestamp | None:
    hit = status_code.index[status_code >= level]
    return hit[0] if len(hit) else None


def naive_threshold_alarm(df: pd.DataFrame, temp_c: float = 80.0, rh_pct: float = 90.0,
                          pd_rate: float = 50.0) -> pd.Timestamp | None:
    """Comparator: the 'just put thresholds on it' system everyone builds first."""
    t = df[["temp_l1_c", "temp_l2_c", "temp_l3_c"]].max(axis=1) > temp_c
    h = df["humidity_internal_pct"] > rh_pct
    p = df["pd_count_per_min"].fillna(0) > pd_rate
    a = df["arc_trip_active"].fillna(0) > 0
    hit = df.index[t | h | p | a] if isinstance(df.index, pd.DatetimeIndex) else df["timestamp"][t | h | p | a]
    return hit[0] if len(hit) else None


def evaluate_run(scored: pd.DataFrame, meta: dict, raw: pd.DataFrame) -> dict:
    onset, failure = meta.get("onset"), meta.get("failure")
    onset = pd.Timestamp(onset) if onset else None
    failure = pd.Timestamp(failure) if failure else None
    sc = scored["status_code"]
    pre = sc[sc.index < onset] if onset is not None else sc
    post = sc[sc.index >= onset] if onset is not None else sc
    # some conditions are WATCH by design (a failed sensor is not a panel emergency)
    level = LEVELS.get(meta.get("detect_level", "WARNING"), WARNING)
    first_watch = first_time_at(post, 1)
    first_warn = first_time_at(post, level)
    benign = meta.get("expected_condition", "NONE") == "NONE"
    # diagnose only while we are actually alarming, not over the recovered tail of the run
    window = scored[scored["status_code"] >= level] if first_warn is not None else scored.iloc[0:0]
    diag = window["condition"].mode()
    naive = naive_threshold_alarm(raw.set_index(pd.DatetimeIndex(raw["timestamp"])))
    pre_days = max((pre.index[-1] - pre.index[0]).total_seconds() / 86400, 1e-6) if len(pre) else 0.0
    return {
        "scenario": meta["scenario"],
        "expected_condition": meta.get("expected_condition", "NONE"),
        "detected": bool(first_warn is not None) if not benign else None,
        "first_watch": first_watch,
        "first_warning": first_warn,
        # lead time is only meaningful against a real failure; otherwise report detection delay after onset
        "lead_time_h": round((failure - first_warn).total_seconds() / 3600, 1)
        if (first_warn is not None and failure is not None) else None,
        "detection_delay_h": round((first_warn - onset).total_seconds() / 3600, 1)
        if (first_warn is not None and onset is not None) else None,
        "naive_lead_time_h": round((failure - naive).total_seconds() / 3600, 1)
        if (naive is not None and failure is not None) else None,
        "naive_detection_delay_h": round((naive - onset).total_seconds() / 3600, 1)
        if (naive is not None and onset is not None) else None,
        "max_status": scored["status"].iloc[np.argmax(sc.to_numpy())] if len(sc) else "NORMAL",
        "max_risk": int(scored["risk"].max()),
        "min_health": int(scored["health"].min()),
        "diagnosis": diag.iloc[0] if len(diag) else None,
        "diagnosis_correct": bool(len(diag) and diag.iloc[0] == meta.get("expected_condition")) if not benign else None,
        "false_warning_episodes_pre_onset": len(episodes(pre, WARNING)),
        "false_warning_per_module_day": round(len(episodes(pre, WARNING)) / pre_days, 3) if pre_days else None,
        "expected_max_status": meta.get("expected_max_status"),
        "detect_level": meta.get("detect_level", "WARNING"),
        # bool(), not numpy.bool_: summing numpy bools ORs them and silently reports "1/9"
        "benign_ok": bool(sc.max() <= {"NORMAL": 0, "WATCH": 1, "WARNING": 2}.get(
            meta.get("expected_max_status", "WATCH"), 1)) if benign else None,
    }


def summarize(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)
