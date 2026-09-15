"""Behaviour tests for the things that would embarrass us in front of the jury."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from grid_up_anomaly_detection.ai.baseline import fit_module_baseline
from grid_up_anomaly_detection.ai.config import SUPPLIED_EXCEL, load_config
from grid_up_anomaly_detection.ai.engine import RiskEngine
from grid_up_anomaly_detection.ai.features import build_features
from grid_up_anomaly_detection.ai.loaders import load_supplied_current, secondary_ma_to_primary_a
from grid_up_anomaly_detection.ai.modbus_maps import (
    NA_SIGNED,
    SCADA_BLOCK_SIZE,
    SCADA_REGISTERS,
    build_scada_block,
    decode_trip_detectors,
    decode_tvoc_system_state,
    module_base_address,
)
from grid_up_anomaly_detection.ai.physics import dew_point_c, rh_from_abs_humidity
from grid_up_anomaly_detection.ai.risk import status_with_hysteresis
from grid_up_anomaly_detection.ai.simulator import ModuleParams, Scenario, simulate

CFG = load_config()


def last_days(df: pd.DataFrame, days: float) -> pd.DataFrame:
    return df[df.index >= df.index[-1] - pd.Timedelta(days=days)]


def run(scn: Scenario, seed: int = 3, mp: ModuleParams | None = None):
    df = simulate(scn, mp or ModuleParams(), seed=seed)
    com = df[df["timestamp"] < df["timestamp"].iloc[0] + pd.Timedelta(days=7)]
    bl = fit_module_baseline(com, CFG, 400.0)
    eng = RiskEngine(CFG, {str(df["module_id"].iloc[0]): bl})
    return df, bl, eng.score(df), eng


# ---------------- supplied data ----------------
def test_current_conversion_matches_sheet_formula():
    assert secondary_ma_to_primary_a(53, 100, 600) == pytest.approx(318)  # sheet row 7: =B7*600000/100/1000


@pytest.mark.skipif(not SUPPLIED_EXCEL.exists(), reason="supplied workbook not present")
def test_supplied_current_loads_with_day_rollover():
    df = load_supplied_current(SUPPLIED_EXCEL)
    assert len(df) == 152
    assert df["timestamp"].is_monotonic_increasing
    assert df["current_l1_a"].between(90, 540).all()


# ---------------- physics ----------------
def test_dew_point_and_rh_are_consistent():
    assert dew_point_c(25.0, 100.0) == pytest.approx(25.0, abs=0.2)
    assert dew_point_c(25.0, 50.0) == pytest.approx(13.9, abs=0.5)
    ah = 9.4  # g/m3
    assert rh_from_abs_humidity(23.0, ah) == pytest.approx(45, abs=3)


def test_baseline_recovers_simulated_thermal_parameters():
    mp = ModuleParams(dT_lug=(30.0, 30.0, 30.0))
    _, bl, _, _ = run(Scenario("n", "normal", days=10, onset_day=None), mp=mp)
    assert bl.valid
    for fit in bl.lug.values():
        assert fit.a == pytest.approx(30.0, rel=0.15)  # learned rise at rated current
        assert fit.r2 > 0.9


# ---------------- detection behaviour ----------------
def test_normal_operation_produces_no_warning():
    _, _, scored, _ = run(Scenario("n", "normal", days=14, onset_day=None))
    assert scored["status_code"].max() <= 1
    assert scored["risk"].median() < 30


def test_loose_connection_warns_well_before_failure():
    scn = Scenario("lc", "loose_connection", days=13, onset_day=8, failure_day=12.6, phase=1)
    df, _, scored, eng = run(scn)
    warn = scored.index[scored["status_code"] >= 2]
    assert len(warn), "loose connection was not detected"
    lead_h = (df.attrs["failure"] - warn[0]).total_seconds() / 3600
    assert lead_h > 24, f"only {lead_h:.1f} h of warning"
    out = eng.output(scored, str(df["module_id"].iloc[0]), scored.index.get_loc(warn[0]))
    assert out["suspected_condition"]["code"] == "LOOSE_CONNECTION"
    assert out["suspected_condition"]["affected_phase"] == "L2"
    assert out["reasons"] and out["reasons"][0]["contribution"] > 0


def test_overload_is_diagnosed_as_overload_not_as_a_fault():
    scn = Scenario("ol", "sustained_overload", days=12, onset_day=8, failure_day=11)
    _, _, scored, _ = run(scn)
    hot = scored[scored["theta"] > 1.1]
    assert len(hot)
    assert (hot["condition"] == "OVERLOAD").mean() > 0.8


def test_ventilation_fault_is_seen_in_cabinet_not_in_phase_asymmetry():
    scn = Scenario("v", "ventilation_degradation", days=13, onset_day=8)
    _, _, scored, _ = run(scn)
    late = last_days(scored, 2)
    assert late["cab_index"].median() > 1.3
    assert late["heat_asym"].median() < 1.2
    assert (late["condition"] == "VENTILATION_DEGRADATION").mean() > 0.5


def test_arc_trip_is_critical_immediately_and_bypasses_models():
    scn = Scenario("a", "sudden_arc", days=10, onset_day=9.3)
    df, _, scored, _ = run(scn)
    at_arc = scored[scored.index >= df.attrs["onset"]]
    assert at_arc["status"].iloc[0] == "CRITICAL"
    assert at_arc["risk"].iloc[0] == 100
    assert at_arc["condition"].iloc[0] == "ARC_FLASH"


def test_single_sample_spike_does_not_raise_a_warning():
    scn = Scenario("b", "benign_transients", days=14, onset_day=None)
    _, _, scored, _ = run(scn)
    assert scored["status_code"].max() <= 1, "benign transients escalated above WATCH"


def test_hot_ambient_day_is_explained_not_alarmed():
    scn = Scenario("h", "hot_ambient", days=12, onset_day=8.4)
    _, _, scored, _ = run(scn)
    assert scored["status_code"].max() <= 1


def test_sensor_fault_is_reported_and_engine_keeps_running():
    scn = Scenario("s", "sensor_fault", days=12, onset_day=8.5, phase=2)
    df, _, scored, eng = run(scn)
    late = last_days(scored, 1)
    assert late["floor_SENSOR_FAULT"].max() > 0
    out = eng.output(scored, str(df["module_id"].iloc[0]))
    assert out["data_quality"]["faulty_channels"]
    assert out["risk_score"] < 60  # a broken sensor is not a panel emergency
    assert out["status"] in ("WATCH", "NORMAL")


# ---------------- engine mechanics ----------------
def test_features_survive_a_coarse_sampling_cadence():
    """Window minimums must follow the *observed* interval, not assume 1-minute data.

    Expressed in samples, a 15-minute cadence silently produced no heating index, no cabinet index
    and no trend slope, and made the slow, quantised cabinet-temperature channel look stuck.
    """
    scn = Scenario("lc", "loose_connection", days=13, onset_day=8, failure_day=12.6, phase=1)
    df = simulate(scn, ModuleParams(), seed=3)
    commissioning = df[df["timestamp"] < df["timestamp"].iloc[0] + pd.Timedelta(days=7)]
    bl = fit_module_baseline(commissioning, CFG, 400.0)

    F = build_features(df.iloc[::15], bl, CFG)          # 15-minute polling
    late = last_days(F, 2)
    assert late["heat_index_max"].notna().mean() > 0.5, "heating index lost at 15-min cadence"
    assert late["cab_index"].notna().mean() > 0.5, "cabinet index lost at 15-min cadence"
    assert late["heat_index_slope"].notna().any(), "trend slope lost at 15-min cadence"

    healthy = F[F.index < df["timestamp"].iloc[0] + pd.Timedelta(days=7)]
    fault_cols = [c for c in healthy.columns if c.startswith("fault_")]
    assert not healthy[fault_cols].to_numpy().any(), "healthy channel reported stuck at 15-min cadence"


def test_simulated_currents_are_never_negative():
    """After an arc trip the breaker opens; measurement noise must not push RMS current below zero."""
    df = simulate(Scenario("a", "sudden_arc", days=10, onset_day=9.3), seed=3)
    for phase in ("l1", "l2", "l3", "n"):
        assert (df[f"current_{phase}_a"].dropna() >= 0).all()


def test_engine_degrades_gracefully_without_baseline_or_ml():
    df = simulate(Scenario("n", "normal", days=9, onset_day=None), seed=5)
    eng = RiskEngine(CFG, {})  # no baseline, no ML
    scored = eng.score(df)
    assert scored["risk"].notna().all()
    out = eng.output(scored, str(df["module_id"].iloc[0]))
    assert out["data_quality"]["baseline_valid"] is False
    assert out["data_quality"]["ml_available"] is False


def test_hysteresis_holds_status_until_risk_stays_low():
    ts = pd.date_range("2026-09-01", periods=120, freq="1min", tz="UTC")
    risk = np.r_[np.full(10, 10), np.full(10, 70), np.full(100, 40)]
    st, _ = status_with_hysteresis(ts, risk, CFG)
    assert st[15] == 2 and st[25] == 2          # still WARNING right after the drop
    assert st[-1] == 1                           # de-escalated to WATCH after the hold time


def test_output_contract_has_the_fields_the_backend_consumes():
    df, _, scored, eng = run(Scenario("lc", "loose_connection", days=13, onset_day=8, failure_day=12.6, phase=1))
    out = eng.output(scored, str(df["module_id"].iloc[0]), -1)
    for k in ["schema_version", "module_id", "panel_id", "timestamp", "status", "status_code", "risk_score",
              "health_score", "confidence", "anomaly_score", "sensor_summary", "suspected_condition",
              "reasons", "recommended_action", "notify", "key_values", "data_quality"]:
        assert k in out, f"missing contract field: {k}"
    assert out["status"] in ("NORMAL", "WATCH", "WARNING", "CRITICAL")
    assert 0 <= out["risk_score"] <= 100 and 0 <= out["health_score"] <= 100
    assert 0.0 <= out["confidence"] <= 1.0
    assert sum(r["contribution"] for r in out["reasons"]) <= 1.01
    for reason in out["reasons"]:
        assert {"code", "source", "severity", "contribution", "message"} <= set(reason)
    for group in ("current", "temperature", "humidity", "partial_discharge", "arc"):
        assert group in out["sensor_summary"]


def test_scada_block_encodes_one_module():
    df, _, scored, eng = run(Scenario("lc", "loose_connection", days=13, onset_day=8, failure_day=12.6, phase=1))
    out = eng.output(scored, str(df["module_id"].iloc[0]), -1)
    regs = build_scada_block(out, heartbeat=7)
    assert len(regs) == SCADA_BLOCK_SIZE and all(0 <= r <= 0xFFFF for r in regs)
    by_name = {r.name: regs[r.offset] for r in SCADA_REGISTERS}
    assert by_name["risk_score"] == out["risk_score"]
    assert by_name["status_code"] == out["status_code"]
    assert by_name["heartbeat"] == 7
    # LV profile has no PD channel -> the register must say "not available", not "zero pulses"
    assert by_name["pd_rate_per_min"] == 0xFFFF
    assert by_name["temp_max_c"] != NA_SIGNED
    assert module_base_address(3) == 1000 + 3 * SCADA_BLOCK_SIZE


def test_streaming_update_matches_batch_scoring():
    df = simulate(Scenario("n", "normal", days=8, onset_day=None), seed=11)
    mid = str(df["module_id"].iloc[0])
    com = df[df["timestamp"] < df["timestamp"].iloc[0] + pd.Timedelta(days=7)]
    bl = fit_module_baseline(com, CFG, 400.0)
    eng = RiskEngine(CFG, {mid: bl})
    tail = df.tail(1500)
    out = None
    for rec in tail.to_dict("records"):
        out = eng.update(rec)
    batch = eng.score(df)
    assert abs(out["risk_score"] - int(batch["risk"].iloc[-1])) <= 5


# ---------------- modbus decoding ----------------
def test_tvoc_decoders_match_the_manual_examples():
    assert decode_tvoc_system_state(0x1) == {"trip_active": True, "error_active": False,
                                             "start_sequence": False, "diagnostics_running": False}
    assert decode_trip_detectors(0b101, 0) == ["X1:1", "X1:3"]
    assert decode_trip_detectors(0, 0b1) == ["X2:6"]
