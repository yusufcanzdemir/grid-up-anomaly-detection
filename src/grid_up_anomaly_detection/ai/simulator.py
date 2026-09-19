"""Deterministic, scenario-driven synthetic data for one monitored circuit (3 phases).

Physics (all parameters are [DEMO] choices):
  cabinet air : dT_int/dt = (T_room + dT_cab * mean((I/Ir)^2) * vent - T_int) / tau_cab
  lug / joint : dT_x/dt   = (T_int + dT_lug_x * (I_x/Ir)^2 * r_x * cu(T_x) - T_x) / tau_lug
                cu(T) = copper resistance temperature coefficient, integrated sample by sample here
                (the detector only sees it through a fitted first-order filter, so it is not scored
                against its own equations)
  humidity    : room absolute humidity (g/m3) is the driver; cabinet RH follows from T_int
                (RH drops when the panel warms -> physically coherent condensation scenarios)
  PD          : Poisson pulse counts, rate grows exponentially during insulation degradation and is
                amplified by humidity
  arc         : TVOC-2 trip -> breaker opens -> currents drop to 0
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .physics import CU_ALPHA, rh_from_abs_humidity


@dataclass
class ModuleParams:
    rated_a: float = 400.0          # [DOC] 1600 kVA feeder DSYA 2-Boy
    load_scale: float = 0.78        # peak-hour load ~ 0.85*0.78 = 66 % of rated
    unbalance: tuple = (1.0, 0.93, 1.07)
    dT_cab: float = 15.0            # K at rated load
    tau_cab: float = 60.0           # min
    dT_lug: tuple = (30.0, 30.0, 30.0)  # K at rated load
    tau_lug: float = 15.0
    room_base: float = 23.0
    room_amp: float = 3.0
    ah_base: float = 9.5            # g/m3 (~45 %RH at 23 C)
    thd_base: float = 9.0


@dataclass
class Scenario:
    name: str
    kind: str
    days: float = 14.0
    onset_day: float | None = 8.0
    failure_day: float | None = None
    profile: str = "LV_PANEL"
    expected_condition: str = "NONE"
    expected_max_status: str = "NORMAL"   # for benign scenarios: the worst acceptable status
    detect_level: str = "WARNING"         # status that counts as "detected" for this scenario
    expected_reasons: tuple[str, ...] = ()  # reason codes a correct detection should surface
    phase: int = 1                        # 0..2, used by phase-specific faults
    extra: dict = field(default_factory=dict)


# Load shape (fraction of peak) at hour knots  [DEMO] mixed residential/commercial feeder
_KNOTS_H = [0, 3, 6, 8, 11, 14, 17, 19, 21, 23, 24]
_KNOTS_V = [0.45, 0.38, 0.45, 0.70, 0.78, 0.74, 0.80, 1.00, 0.95, 0.62, 0.45]


def _ar1(n: int, tau_min: float, sigma: float, rng: np.random.Generator) -> np.ndarray:
    phi = np.exp(-1.0 / tau_min)
    e = rng.normal(0, sigma * np.sqrt(1 - phi ** 2), n)
    out = np.empty(n)
    acc = 0.0
    for i in range(n):
        acc = phi * acc + e[i]
        out[i] = acc
    return out


def _ramp(t_d: np.ndarray, start: float, end: float) -> np.ndarray:
    """0 before start, linear to 1 at end, 1 after."""
    return np.clip((t_d - start) / max(end - start, 1e-9), 0.0, 1.0)


def simulate(scn: Scenario, mp: ModuleParams | None = None, seed: int = 42,
             start: str = "2026-09-01", module_id: str = "M-001", panel_id: str = "P-001",
             site_id: str = "SITE-01") -> pd.DataFrame:
    mp = mp or ModuleParams()
    rng = np.random.default_rng(seed)
    n = int(scn.days * 1440)
    t_min = np.arange(n, dtype=float)
    t_d = t_min / 1440.0
    hod = (t_min / 60.0) % 24
    ts = pd.date_range(start, periods=n, freq="1min", tz="UTC")
    weekday = ts.dayofweek.to_numpy()
    onset = scn.onset_day if scn.onset_day is not None else np.inf
    fail = scn.failure_day if scn.failure_day is not None else np.inf
    ex = scn.extra

    # ---------------- load ----------------
    shape = np.interp(hod, _KNOTS_H, _KNOTS_V) * np.where(weekday >= 5, 0.88, 1.0)
    load = mp.load_scale * shape * (1 + _ar1(n, 60, 0.04, rng))
    if scn.kind == "sustained_overload":
        load *= 1 + (ex.get("factor", 1.45) - 1) * _ramp(t_d, onset, onset + 0.5) * (t_d < fail)
    if scn.kind == "condensation":
        load *= 1 - 0.55 * ((t_d >= onset) & (t_d < onset + ex.get("dur_d", 2.5)))  # holiday / low load
    if scn.kind == "benign_transients":
        # cold-load pickup after a restoration: brief, but stays below the thermal-image alarm.
        # (A *sustained* 1.3 pu load is not benign and is expected to alarm - see sustained_overload.)
        for d in ex.get("pickup_days", [8.3, 10.8]):
            load = np.where((t_d >= d) & (t_d < d + 20 / 1440), 1.15, load)
    currents = np.stack([mp.rated_a * load * u * (1 + rng.normal(0, 0.005, n)) for u in mp.unbalance])
    tripped = t_d >= fail if scn.kind in ("loose_connection", "insulation_degradation", "sudden_arc") else np.zeros(n, bool)
    if scn.kind == "sudden_arc":
        tripped = t_d >= onset
    currents[:, tripped] = 0.0

    # ---------------- environment ----------------
    room = mp.room_base + mp.room_amp * np.sin(2 * np.pi * (hod - 9) / 24) + _ar1(n, 180, 0.6, rng)
    ah = mp.ah_base + 0.8 * np.sin(2 * np.pi * (hod - 14) / 24) + _ar1(n, 600, 0.8, rng)
    if scn.kind == "hot_ambient":
        hw = (t_d >= onset) & (t_d < onset + ex.get("dur_d", 2.0))
        room = room + 13.0 * hw * np.clip(np.sin(np.pi * (hod - 6) / 16), 0.2, 1.0)  # up to ~39 C (spec max 40)
    if scn.kind == "condensation":
        wet = _ramp(t_d, onset, onset + 0.4) * (t_d < onset + ex.get("dur_d", 2.5))
        room = room - 7.0 * wet                     # cold, rainy spell
        ah = ah + 5.0 * wet                         # moist air ingress
    if scn.kind == "insulation_degradation":
        ah = ah + 3.5 * _ramp(t_d, onset - 1, onset) * (1 + 0.5 * np.sin(2 * np.pi * t_d / 2.3))
    room = np.clip(room, -5, 40)                    # [DOC] indoor ambient envelope

    # ---------------- thermal state machine ----------------
    r = np.ones((3, n))
    vent = np.ones(n)
    if scn.kind == "loose_connection":
        x = _ramp(t_d, onset, fail)
        r[scn.phase] = 1 + (ex.get("r_max", 4.0) - 1) * x ** 2.2   # accelerating contact degradation
    if scn.kind == "ventilation_degradation":
        vent = 1 + (ex.get("vent_max", 1.9) - 1) * _ramp(t_d, onset, scn.days)
    ipu2 = (currents / mp.rated_a) ** 2
    t_int = np.empty(n)
    t_lug = np.empty((3, n))
    ti = room[0] + mp.dT_cab * ipu2[:, 0].mean()
    tl = np.array([ti + mp.dT_lug[k] * ipu2[k, 0] for k in range(3)])
    a_cab = 1 - np.exp(-1 / mp.tau_cab)
    a_lug = 1 - np.exp(-1 / mp.tau_lug)
    for i in range(n):
        extra_heat = sum(mp.dT_lug[k] * ipu2[k, i] * (r[k, i] - 1) for k in range(3)) * 0.08
        ti += a_cab * (room[i] + mp.dT_cab * ipu2[:, i].mean() * vent[i] + extra_heat - ti)
        for k in range(3):
            cu = (1 + CU_ALPHA * (tl[k] - 20)) / (1 + CU_ALPHA * 30)
            tl[k] += a_lug * (ti + mp.dT_lug[k] * ipu2[k, i] * r[k, i] * cu - tl[k])
        t_int[i] = ti
        t_lug[:, i] = tl
    rh = rh_from_abs_humidity(t_int, ah)

    def meas(x, sigma, q):
        return np.round((x + rng.normal(0, sigma, np.shape(x))) / q) * q

    df = pd.DataFrame({
        "timestamp": ts, "site_id": site_id, "panel_id": panel_id, "module_id": module_id,
        "profile": scn.profile,
        # clipped at 0: a real RMS ammeter cannot report negative current, and after an arc trip the
        # measurement noise would otherwise push zeroed currents below zero
        "current_l1_a": np.clip(meas(currents[0], 0.5, 0.1), 0, None),
        "current_l2_a": np.clip(meas(currents[1], 0.5, 0.1), 0, None),
        "current_l3_a": np.clip(meas(currents[2], 0.5, 0.1), 0, None),
        "temp_l1_c": meas(t_lug[0], 0.15, 0.1), "temp_l2_c": meas(t_lug[1], 0.15, 0.1),
        "temp_l3_c": meas(t_lug[2], 0.15, 0.1),
        "temp_internal_c": meas(t_int, 0.1, 0.1), "humidity_internal_pct": np.clip(meas(rh, 0.8, 0.1), 0, 100),
        "temp_ambient_c": meas(room, 0.1, 0.1),
    })
    # neutral: fundamental phasor imbalance + triplen harmonics
    ph = np.exp(1j * np.array([0, -2 * np.pi / 3, 2 * np.pi / 3]))[:, None]
    thd = np.clip(mp.thd_base + 2 * (1 - shape) + _ar1(n, 120, 0.8, rng), 2, 40)
    fund = np.abs((currents * ph).sum(0))
    trip = currents.mean(0) * 3 * 0.4 * thd / 100
    df["current_n_a"] = np.clip(meas(np.sqrt(fund ** 2 + trip ** 2), 0.5, 0.1), 0, None)
    df["current_thd_pct"] = np.round(thd, 1)

    # ---------------- partial discharge (MV_CELL only) ----------------
    if scn.profile == "MV_CELL":
        lam = np.full(n, 0.3)
        if scn.kind == "insulation_degradation":
            x = _ramp(t_d, onset, fail)
            lam = 0.3 * np.exp(np.log(ex.get("pd_rate_final", 150) / 0.3) * x ** 1.5)
        lam = lam * (1 + 1.5 * np.clip((rh - 50) / 40, 0, 1))
        lam[tripped] = 0
        cnt = rng.poisson(lam)
        amp_scale = 4 + (60 * _ramp(t_d, onset, fail) if scn.kind == "insulation_degradation" else 0)
        peak = np.where(cnt > 0, amp_scale * rng.lognormal(0, 0.3, n) + 3, rng.normal(3, 0.4, n))
        df["pd_count_per_min"] = cnt.astype(float)
        df["pd_peak_mv"] = np.round(np.clip(peak, 0, None), 1)
    else:
        df["pd_count_per_min"] = np.nan
        df["pd_peak_mv"] = np.nan

    # ---------------- arc (TVOC-2) ----------------
    arc_active = np.zeros(n)
    arc_count = np.zeros(n)
    if scn.kind in ("loose_connection", "insulation_degradation", "sudden_arc") and np.isfinite(
            fail if scn.kind != "sudden_arc" else onset):
        t_arc = onset if scn.kind == "sudden_arc" else fail
        arc_active[t_d >= t_arc] = 1
        arc_count[t_d >= t_arc] = 1
    # mode 1: arc detected, trip circuit not fired -> breaker stays closed, currents keep flowing
    arc_no_trip = np.zeros(n)
    if scn.kind == "arc_no_trip" and np.isfinite(onset):
        arc_no_trip[t_d >= onset] = 1
    df["arc_trip_active"] = arc_active
    df["arc_trip_count"] = arc_count
    df["arc_detected_no_trip"] = arc_no_trip
    df["arc_trip_relays"] = np.where(arc_active > 0, 1.0, 0.0)
    df["arc_system_error"] = 0.0
    df["arc_light_warning"] = 0.0

    # ---------------- sensor / measurement faults ----------------
    if scn.kind == "sensor_fault":
        k = f"temp_l{scn.phase + 1}_c"
        stuck = (t_d >= onset) & (t_d < onset + 1.5)
        idx = np.argmax(stuck)
        df.loc[stuck, k] = df[k].iloc[idx]
        df.loc[t_d >= onset + 1.5, k] = np.nan
    if scn.kind == "benign_transients":
        for d in ex.get("spike_days", [8.1, 9.45, 11.2, 12.7]):
            i = int(d * 1440)
            df.loc[i, "temp_l1_c"] += 25.0          # single-sample EMI spike
        i = int(ex.get("dropout_day", 10.2) * 1440)
        df.loc[i:i + 7, ["temp_internal_c", "humidity_internal_pct"]] = np.nan  # 8-min comms dropout

    # ---------------- ground truth ----------------
    benign = scn.kind in ("normal", "hot_ambient", "benign_transients")
    df["gt_scenario"] = scn.name
    df["gt_anomaly"] = (not benign) and (t_d >= onset)
    df["gt_failure"] = t_d >= fail if np.isfinite(fail) else False
    if scn.kind in ("sudden_arc", "arc_no_trip"):
        df["gt_failure"] = t_d >= onset
    df.attrs.update(scenario=scn.name, kind=scn.kind, onset=ts[0] + pd.Timedelta(days=onset) if np.isfinite(onset) else None,
                    failure=ts[0] + pd.Timedelta(days=fail) if np.isfinite(fail) else None, rated_a=mp.rated_a)
    return df


def scenario_library() -> list[Scenario]:
    """Scenarios defensible from the supplied material (scenario matrix in docs/scada_mapping.md)."""
    return [
        Scenario("loose_connection", "loose_connection", days=13, onset_day=8, failure_day=12.6,
                 expected_condition="LOOSE_CONNECTION", phase=1,
                 expected_reasons=("PHASE_ASYMMETRY", "CONNECTION_HEATING", "LUG_RESIDUAL", "HEATING_TREND")),
        Scenario("ventilation_failure", "ventilation_degradation", days=13, onset_day=8,
                 expected_condition="VENTILATION_DEGRADATION", expected_reasons=("CABINET_HEATING",)),
        Scenario("sustained_overload", "sustained_overload", days=12, onset_day=8, failure_day=11,
                 expected_condition="OVERLOAD",
                 expected_reasons=("THERMAL_OVERLOAD", "OVERLOAD_RULE", "ABS_TEMPERATURE")),
        Scenario("high_humidity_condensation", "condensation", days=12, onset_day=8.2,
                 expected_condition="CONDENSATION_RISK",
                 expected_reasons=("CONDENSATION", "HUMIDITY_HIGH", "CONDENSATION_RULE")),
        Scenario("developing_partial_discharge", "insulation_degradation", days=14, onset_day=8,
                 failure_day=13.5, profile="MV_CELL", expected_condition="INSULATION_DEGRADATION",
                 expected_reasons=("PD_ACTIVITY", "PD_TREND")),
        Scenario("arc_event", "sudden_arc", days=10, onset_day=9.3, expected_condition="ARC_FLASH",
                 expected_reasons=("ARC_TRIP",)),
        # arc detected without a trip: breaker stays closed, load keeps flowing, still CRITICAL
        Scenario("arc_detected_no_trip", "arc_no_trip", days=10, onset_day=9.3,
                 expected_condition="ARC_FLASH", detect_level="CRITICAL",
                 expected_reasons=("ARC_DETECTED_NO_TRIP",)),
        # a dead sensor must be reported, but it is an operations issue - WATCH is the correct ceiling
        Scenario("sensor_failure", "sensor_fault", days=12, onset_day=8.5, expected_condition="SENSOR_FAULT",
                 phase=2, detect_level="WATCH", expected_reasons=("SENSOR_FAULT",)),
        Scenario("benign_transient", "benign_transients", days=14, onset_day=None, expected_max_status="WATCH"),
        Scenario("hot_ambient_day", "hot_ambient", days=12, onset_day=8.4, expected_max_status="WATCH"),
        Scenario("normal_operation", "normal", days=14, onset_day=None, expected_max_status="WATCH"),
        Scenario("normal_operation_mv", "normal", days=14, onset_day=None, profile="MV_CELL",
                 expected_max_status="WATCH"),
    ]


def fleet_params(n: int, seed: int = 7) -> list[ModuleParams]:
    """Module-to-module variation so per-module calibration matters."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        out.append(ModuleParams(
            load_scale=float(rng.uniform(0.6, 0.85)), dT_cab=float(rng.uniform(11, 19)),
            tau_cab=float(rng.uniform(45, 90)), dT_lug=tuple(float(v) for v in rng.uniform(24, 36, 3)),
            tau_lug=float(rng.uniform(10, 25)), room_base=float(rng.uniform(19, 26)),
            ah_base=float(rng.uniform(7.5, 11.0)),
            unbalance=tuple(float(v) for v in rng.uniform(0.9, 1.1, 3)),
        ))
    return out
