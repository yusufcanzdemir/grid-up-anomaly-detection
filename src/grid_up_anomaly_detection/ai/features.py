"""Feature pipeline: canonical rows of ONE module -> physics-informed features.

Same function is used for training, batch evaluation and streaming (on a rolling buffer),
so there is no train/serve skew.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .baseline import ModuleBaseline, minutes_since_start
from .physics import copper_factor, dew_point_c, first_order
from .schema import CHANNEL_COLUMNS, PHASES

LUG_COLS = [f"temp_{p}_c" for p in PHASES]
MONITORED_CHANNELS = LUG_COLS + ["temp_internal_c", "humidity_internal_pct", "temp_ambient_c",
                                 "current_l1_a", "current_l2_a", "current_l3_a", "pd_count_per_min"]


def sampling_minutes(index: pd.DatetimeIndex) -> float:
    """Observed sampling interval. Features must not assume the canonical 1-minute grid: a field
    deployment may poll every 5 min, and window minimums expressed in *samples* would silently
    disable the heating index and the trend slopes."""
    if len(index) < 3:
        return 1.0
    dt = pd.Series(index).diff().dt.total_seconds().median() / 60.0
    return float(dt) if dt and dt > 0 else 1.0


def min_samples(window_min: float, dt_min: float, frac: float, floor: int = 3) -> int:
    """How many samples a time window must contain before its statistic is trustworthy."""
    return max(floor, int(frac * window_min / max(dt_min, 1e-9)))


def rolling_slope(y: pd.Series, window: str, dt_min: float = 1.0, min_frac: float = 0.5) -> pd.Series:
    """Least-squares slope per day over a trailing time window (NaN-aware).

    min_frac guards against slopes extrapolated from a nearly empty window (a 24 h trend
    estimated from 30 minutes of data is noise, and it used to raise false PD warnings).
    """
    t = pd.Series((y.index - y.index[0]).total_seconds() / 86400.0, index=y.index).where(y.notna())
    need = min_samples(pd.Timedelta(window).total_seconds() / 60, dt_min, min_frac, floor=5)
    r = lambda s: s.rolling(window, min_periods=need).mean()  # noqa: E731
    mx, my, mxy, mxx = r(t), r(y), r(t * y), r(t * t)
    var = mxx - mx ** 2
    return ((mxy - mx * my) / var.where(var > 1e-6)).astype(float)


def _sensor_health(df: pd.DataFrame, cfg: dict, dt_min: float, known: set[str] = frozenset()) -> pd.DataFrame:
    """`known`: channels this module has reported before (streaming). A sensor that died longer ago than
    the rolling buffer has no values left in it and must still count as installed, i.e. as faulty."""
    f = cfg["features"]
    floor = f.get("stuck_min_samples", 12)
    # widen the window if the cadence is coarse, so "stuck" always means at least `floor` samples
    window_min = max(f["stuck_window_min"], dt_min * floor)
    w = f"{window_min:g}min"
    need = max(floor, min_samples(window_min, dt_min, 0.5))
    out = pd.DataFrame(index=df.index)
    for c in MONITORED_CHANNELS:
        s = df[c]
        installed = s.notna().cummax().astype(bool) | (c in known)  # once seen, losing it is a fault
        missing = s.isna().astype(float).rolling("30min", min_periods=1).mean() > 0.5
        stuck = (s.rolling(w, min_periods=need).std() < f["stuck_std_eps"])
        if c.startswith("current") or c.startswith("pd_"):
            stuck = stuck & (s > 0)  # zero current / zero PD is legitimately flat
        out[f"fault_{c}"] = installed & (missing | stuck)
    return out


def build_features(df: pd.DataFrame, bl: ModuleBaseline | None, cfg: dict) -> pd.DataFrame:
    f = cfg["features"]
    known = set(df.attrs.get("installed_channels", ()))
    df = df.set_index(pd.DatetimeIndex(df["timestamp"])).sort_index()
    t = minutes_since_start(df.index)
    rated = bl.rated_a if bl else float(df.attrs.get("rated_a", 400.0))
    dt_min = sampling_minutes(df.index)
    F = pd.DataFrame(index=df.index)
    health = _sensor_health(df, cfg, dt_min, known)
    F = F.join(health)

    # --- spike-filtered temperatures (median filter removes single-sample EMI spikes)
    med = f"{f['spike_median_min']}min"
    temps = {}
    for c in LUG_COLS + ["temp_internal_c", "temp_ambient_c"]:
        s = df[c].rolling(med, min_periods=1).median()
        temps[c] = s.where(~health[f"fault_{c}"])
    t_int = temps["temp_internal_c"]
    t_room = temps["temp_ambient_c"]

    # --- electrical
    ipu2 = {p: (df[f"current_{p}_a"] / rated) ** 2 for p in PHASES}
    ipu2_df = pd.DataFrame(ipu2)
    F["current_max_pu"] = np.sqrt(ipu2_df.max(axis=1))
    F["theta"] = first_order(ipu2_df.max(axis=1).to_numpy(), t, f["thermal_image_tau_min"])
    i_mean = df[[f"current_{p}_a" for p in PHASES]].mean(axis=1)
    F["neutral_ratio"] = (df["current_n_a"] / i_mean).where(i_mean > 0.1 * rated)
    F["current_thd_pct"] = df["current_thd_pct"]

    # --- lug thermal residuals and load-normalised heating index
    min_u = cfg["baseline"]["min_load_pu2"]
    min_rise = cfg["baseline"]["min_rise_k"]
    smooth = f"{f['heating_index_smooth_min']}min"
    smooth_min_periods = min_samples(f["heating_index_smooth_min"], dt_min, 0.5)
    ffill_n = max(1, int(f["heating_index_ffill_h"] * 60 / dt_min))   # samples, derived from the real cadence
    for p, c in zip(PHASES, LUG_COLS):
        fit = bl.lug.get(p) if bl else None
        if fit is None:
            F[f"lug_resid_z_{p}"] = np.nan
            F[f"heat_index_{p}"] = np.nan
            continue
        u = pd.Series(first_order((ipu2[p] * copper_factor(temps[c])).to_numpy(), t, fit.tau), index=df.index)
        y = temps[c] - t_int
        resid = y - fit.predict(u)
        F[f"lug_resid_{p}"] = resid
        F[f"lug_resid_z_{p}"] = resid / fit.sigma
        # a ratio is only measurable when the expected rise is big enough to measure
        hi = ((y - fit.b) / (fit.a * u)).where((u >= min_u) & (fit.a * u >= min_rise))
        F[f"heat_index_{p}"] = hi.rolling(smooth, min_periods=smooth_min_periods).median().ffill(limit=ffill_n)
    hi_cols = [f"heat_index_{p}" for p in PHASES]
    his = F[hi_cols]
    F["heat_index_max"] = his.max(axis=1)
    F["heat_asym"] = (his.max(axis=1) / his.median(axis=1)).where(his.notna().sum(axis=1) >= 2)
    any_hi = his.notna().any(axis=1)
    hot = pd.Series(np.array(PHASES)[np.nanargmax(his.fillna(-np.inf).to_numpy(), axis=1)], index=df.index)
    F["hot_phase"] = hot.where(any_hi).str.upper()
    F["lug_resid_z_max"] = F[[f"lug_resid_z_{p}" for p in PHASES]].max(axis=1)
    F["heat_index_slope"] = rolling_slope(F["heat_index_max"], f"{f['trend_window_h']}h", dt_min).clip(lower=0)

    # --- cabinet / ventilation
    if bl and bl.cab is not None:
        u_cab = pd.DataFrame({p: ipu2[p] * copper_factor(temps[c]) for p, c in zip(PHASES, LUG_COLS)}).mean(axis=1)
        u = pd.Series(first_order(u_cab.to_numpy(), t, bl.cab.tau), index=df.index)
        y = t_int - t_room
        F["cab_resid_z"] = (y - bl.cab.predict(u)) / bl.cab.sigma
        ci = ((y - bl.cab.b) / (bl.cab.a * u)).where((u >= min_u) & (bl.cab.a * u >= min_rise))
        F["cab_index"] = ci.rolling(smooth, min_periods=smooth_min_periods).median().ffill(limit=ffill_n)
    else:
        F["cab_resid_z"] = np.nan
        F["cab_index"] = np.nan

    # --- environment
    F["temp_max_f"] = pd.DataFrame({c: temps[c] for c in LUG_COLS}).max(axis=1)
    F["temp_internal_c"] = t_int
    F["rh"] = df["humidity_internal_pct"].rolling("10min", min_periods=1).mean().where(
        ~health["fault_humidity_internal_pct"])
    dp = pd.Series(dew_point_c(t_int, F["rh"]), index=df.index)
    coldest = t_room.where(t_room.notna(), t_int)          # enclosure wall ~ room temperature
    F["dew_point_c"] = dp
    F["dew_margin_c"] = np.minimum(coldest, t_int) - dp

    # --- partial discharge
    pdw = f"{f['pd_window_min']}min"
    pd_min_periods = min_samples(f["pd_window_min"], dt_min, 0.2, floor=2)
    pd_rate = df["pd_count_per_min"].rolling(pdw, min_periods=pd_min_periods).mean()
    F["pd_rate"] = pd_rate
    F["pd_peak_mv"] = df["pd_peak_mv"].rolling(pdw, min_periods=pd_min_periods).max()
    if bl and bl.pd_median is not None:
        lg = np.log1p(pd_rate)
        F["pd_z"] = (lg - bl.pd_median) / bl.pd_scale
        # a rising trend only matters if the level itself has moved off the baseline
        F["pd_slope"] = rolling_slope(lg, f"{f['trend_window_h']}h", dt_min).clip(lower=0).where(F["pd_z"] > 1.0, 0.0)
        F["pd_rh_corr"] = pd_rate.rolling(
            f"{f['pd_corr_window_h']}h",
            min_periods=min_samples(f["pd_corr_window_h"] * 60, dt_min, 0.2, floor=10)).corr(F["rh"])
    else:
        F["pd_z"] = np.nan
        F["pd_slope"] = np.nan
        F["pd_rh_corr"] = np.nan

    # --- arc events (TVOC-2)
    F["arc_trip_active"] = df["arc_trip_active"].fillna(0)
    F["arc_trip_new"] = (df["arc_trip_count"].ffill().diff().fillna(0) > 0).astype(float)
    F["arc_detected_no_trip"] = df["arc_detected_no_trip"].fillna(0)
    F["arc_system_error"] = df["arc_system_error"].fillna(0)
    F["arc_light_warning"] = df["arc_light_warning"].fillna(0)

    # --- raw channel passthrough, so the inference payload can report what the sensors actually said
    for c in CHANNEL_COLUMNS:
        F[f"raw_{c}"] = df[c]

    # --- data quality
    profile_cols = [c for c in MONITORED_CHANNELS if df[c].notna().any() or c in known]
    F["completeness"] = df[profile_cols].notna().mean(axis=1) if profile_cols else 0.0
    F["baseline_valid"] = bool(bl.valid) if bl else False
    return F
