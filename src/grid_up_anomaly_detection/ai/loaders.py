"""Loader for the supplied Excel workbook (Istenen Veriler.xlsx)."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from .config import SUPPLIED_EXCEL

CURRENT_SHEET = "Akım Sensörü"
FIRST_DATA_ROW = 7  # rows 1-6 are titles / headers


def secondary_ma_to_primary_a(ma: float | pd.Series, secondary_fs_ma: float, primary_fs_a: float):
    """Linear CT conversion. Sheet: 100 mA <-> 600 A, i.e. I_p = mA * 600000/100 / 1000."""
    return ma * (primary_fs_a / secondary_fs_ma)


def _time_of_day(v) -> dt.time:
    # Excel stores the first day as time objects and after midnight as datetime(1900-01-01, ...)
    return v.time() if isinstance(v, dt.datetime) else v


def load_supplied_current(path: str | Path = SUPPLIED_EXCEL, start_date: str = "2026-09-01",
                          secondary_fs_ma: float = 100, primary_fs_a: float = 600) -> pd.DataFrame:
    """Return [timestamp, current_l1_ma, current_l1_a] with day roll-over reconstructed.

    start_date is arbitrary: the sheet has time-of-day only.
    """
    raw = pd.read_excel(path, sheet_name=CURRENT_SHEET, header=None, skiprows=FIRST_DATA_ROW - 1,
                        usecols="A:B", names=["tod", "ma"]).dropna()
    day = 0
    prev = None
    stamps = []
    base = pd.Timestamp(start_date, tz="UTC")
    for v in raw["tod"]:
        t = _time_of_day(v)
        if prev is not None and t <= prev:
            day += 1
        prev = t
        stamps.append(base + pd.Timedelta(days=day, hours=t.hour, minutes=t.minute, seconds=t.second))
    ma = raw["ma"].astype(float).to_numpy()
    return pd.DataFrame({
        "timestamp": stamps,
        "current_l1_ma": ma,
        "current_l1_a": secondary_ma_to_primary_a(ma, secondary_fs_ma, primary_fs_a),
    })
