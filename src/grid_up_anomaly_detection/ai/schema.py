"""Canonical sensor-reading schema (one row = one module at one timestamp).

Missing / not-installed channels are NaN. Nothing downstream may assume a channel exists.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ID_COLUMNS = ["timestamp", "site_id", "panel_id", "module_id", "profile"]

# column -> (unit, source)
CHANNELS: dict[str, tuple[str, str]] = {
    # electrical: MPR-53CS energy analyzer (Modbus RTU, already mandated by the panel spec)
    "current_l1_a": ("A", "MPR-53CS reg 6"),
    "current_l2_a": ("A", "MPR-53CS reg 8"),
    "current_l3_a": ("A", "MPR-53CS reg 10"),
    "current_n_a": ("A", "MPR-53CS reg 12"),
    "current_thd_pct": ("%", "MPR-53CS reg 78-82 (max of phases)"),
    # thermal: new module sensors
    "temp_l1_c": ("degC", "connection/lug surface sensor L1, external probe, >=125 degC range"),
    "temp_l2_c": ("degC", "connection/lug surface sensor L2, external probe, >=125 degC range"),
    "temp_l3_c": ("degC", "connection/lug surface sensor L3, external probe, >=125 degC range"),
    "temp_internal_c": ("degC", "cabinet air sensor"),
    "humidity_internal_pct": ("%RH", "cabinet air sensor"),
    "temp_ambient_c": ("degC", "room / outside-cabinet sensor (optional)"),
    # discharge: HFCT + acquisition front-end (optional, MV_CELL profile)
    "pd_count_per_min": ("1/min", "HFCT pulses above noise threshold"),
    "pd_peak_mv": ("mV", "HFCT max pulse amplitude @50 ohm"),
    # arc: ABB TVOC-2-COM (Modbus RTU)
    "arc_trip_active": ("bool", "TVOC-2 reg 1300 bit0"),
    # Arc mode 1: detected, trip circuit not fired. No mode register exists in the manual, so the
    # field module derives it from reg 210/211 non-zero while reg 212 == 0. Verify on real hardware.
    "arc_detected_no_trip": ("bool", "TVOC-2 reg 210/211 set while reg 212 == 0 [ASSUMPTION]"),
    "arc_trip_relays": ("bitfield", "TVOC-2 reg 212, bit0=K4 bit1=K5 bit2=K6"),
    "arc_trip_count": ("count", "TVOC-2 reg 149"),
    "arc_system_error": ("bool", "TVOC-2 reg 1300 bit1"),
    "arc_light_warning": ("bool", "TVOC-2 reg 224/225"),
}
CHANNEL_COLUMNS = list(CHANNELS)
CANONICAL_COLUMNS = ID_COLUMNS + CHANNEL_COLUMNS
PHASES = ("l1", "l2", "l3")
TEMP_COLUMNS = ["temp_l1_c", "temp_l2_c", "temp_l3_c", "temp_internal_c", "temp_ambient_c"]

PROFILES = {
    # LV panel: current from existing analyzer, 3 lug temps, cabinet T/RH, room T, arc via TVOC-2
    "LV_PANEL": [c for c in CHANNEL_COLUMNS if not c.startswith("pd_")],
    # MV cell: + partial discharge
    "MV_CELL": CHANNEL_COLUMNS,
}


def empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=CANONICAL_COLUMNS)


def validate(df: pd.DataFrame, cfg: dict, rated_a: float) -> pd.DataFrame:
    """Coerce to canonical schema; physically implausible values become NaN."""
    out = df.copy()
    for c in CANONICAL_COLUMNS:
        if c not in out:
            out[c] = np.nan
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    out = out.sort_values("timestamp").drop_duplicates(["module_id", "timestamp"])
    v = cfg["validation"]
    lo, hi = v["temp_c"]
    for c in TEMP_COLUMNS:
        out[c] = pd.to_numeric(out[c], errors="coerce").where(lambda s: s.between(lo, hi))
    h_lo, h_hi = v["humidity_pct"]
    out["humidity_internal_pct"] = pd.to_numeric(out["humidity_internal_pct"], errors="coerce").where(
        lambda s: s.between(h_lo, h_hi))
    imax = v["current_pu_max"] * rated_a
    for c in ["current_l1_a", "current_l2_a", "current_l3_a", "current_n_a"]:
        out[c] = pd.to_numeric(out[c], errors="coerce").where(lambda s: s.between(0, imax))
    p_lo, p_hi = v["pd_count_per_min"]
    out["pd_count_per_min"] = pd.to_numeric(out["pd_count_per_min"], errors="coerce").where(
        lambda s: s.between(p_lo, p_hi))
    return out[CANONICAL_COLUMNS].reset_index(drop=True)
