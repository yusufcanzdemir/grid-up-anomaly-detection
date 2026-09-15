"""Per-module learned thermal baseline (commissioning window).

For each lug:     T_x - T_int  ~= a * LPF_tau((I_x/Ir)^2) + b
For the cabinet:  T_int - T_room ~= a * LPF_tau(mean_x (I_x/Ir)^2) + b
tau is chosen by grid search, (a, b) by least squares. sigma = robust (MAD) residual scale.
Interpretation: a = temperature rise at rated current, i.e. the module's own "thermal signature".
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .physics import copper_factor, first_order
from .schema import PHASES


@dataclass
class ThermalFit:
    a: float
    b: float
    tau: float
    sigma: float
    r2: float

    def predict(self, u_filtered: np.ndarray) -> np.ndarray:
        return self.a * u_filtered + self.b


@dataclass
class ModuleBaseline:
    module_id: str
    rated_a: float
    lug: dict[str, ThermalFit | None] = field(default_factory=dict)
    cab: ThermalFit | None = None
    pd_median: float | None = None
    pd_scale: float | None = None
    valid: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ModuleBaseline":
        lug = {k: ThermalFit(**v) if v else None for k, v in d["lug"].items()}
        cab = ThermalFit(**d["cab"]) if d.get("cab") else None
        return cls(d["module_id"], d["rated_a"], lug, cab, d.get("pd_median"), d.get("pd_scale"), d["valid"])


def minutes_since_start(ts: pd.Series | pd.DatetimeIndex) -> np.ndarray:
    ts = pd.DatetimeIndex(ts)
    return ((ts - ts[0]).total_seconds() / 60.0).to_numpy()


def fit_first_order(y: np.ndarray, u_raw: np.ndarray, t_min: np.ndarray, taus: list[float]) -> ThermalFit | None:
    best = None
    for tau in taus:
        u = first_order(u_raw, t_min, tau)
        m = ~(np.isnan(y) | np.isnan(u))
        if m.sum() < 500 or np.nanstd(u[m]) < 1e-3:
            continue
        A = np.column_stack([u[m], np.ones(m.sum())])
        coef, *_ = np.linalg.lstsq(A, y[m], rcond=None)
        res = y[m] - A @ coef
        mse = float(np.mean(res ** 2))
        if best is None or mse < best[0]:
            sigma = 1.4826 * float(np.median(np.abs(res - np.median(res))))
            r2 = 1 - mse / float(np.var(y[m]))
            best = (mse, ThermalFit(float(coef[0]), float(coef[1]), float(tau), max(sigma, 0.2), float(r2)))
    return best[1] if best else None


def fit_module_baseline(df: pd.DataFrame, cfg: dict, rated_a: float) -> ModuleBaseline:
    """df: canonical rows of ONE module during normal operation (commissioning)."""
    taus = cfg["baseline"]["tau_grid_min"]
    t = minutes_since_start(df["timestamp"])
    t_int = df["temp_internal_c"].to_numpy(float)
    ipu2 = {p: (df[f"current_{p}_a"].to_numpy(float) / rated_a) ** 2 for p in PHASES}
    bl = ModuleBaseline(str(df["module_id"].iloc[0]), rated_a)
    for p in PHASES:
        t_lug = df[f"temp_{p}_c"].to_numpy(float)
        y = t_lug - t_int
        bl.lug[p] = fit_first_order(y, ipu2[p] * copper_factor(t_lug), t, taus)
    if df["temp_ambient_c"].notna().mean() > 0.5:
        y = t_int - df["temp_ambient_c"].to_numpy(float)
        u_cab = np.nanmean(np.stack([ipu2[p] * copper_factor(df[f"temp_{p}_c"].to_numpy(float)) for p in PHASES]), 0)
        bl.cab = fit_first_order(y, u_cab, t, taus)
    pd_rate = df["pd_count_per_min"]
    if pd_rate.notna().mean() > 0.5:
        s = np.log1p(pd_rate.rolling(cfg["features"]["pd_window_min"], min_periods=5).mean().dropna())
        bl.pd_median = float(s.median())
        bl.pd_scale = max(1.4826 * float((s - s.median()).abs().median()), 0.1)
    fits = [f for f in bl.lug.values() if f is not None]
    bl.valid = len(fits) >= 2 and all(f.r2 >= cfg["baseline"]["min_r2"] for f in fits)
    return bl


def save_baselines(bls: dict[str, ModuleBaseline], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({k: v.to_dict() for k, v in bls.items()}, indent=2))


def load_baselines(path: Path) -> dict[str, ModuleBaseline]:
    return {k: ModuleBaseline.from_dict(v) for k, v in json.loads(path.read_text()).items()}
