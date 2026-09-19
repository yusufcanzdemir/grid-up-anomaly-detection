"""Modbus maps, in two clearly separated halves.

READ side  - registers that already exist on devices in the panel, transcribed from the supplied
             manuals (MPR-53CS register map, ABB TVOC-2-COM manual 1SFC170017M0201 Rev D).
WRITE side - OUR PROPOSED output block. It is a proposal from this project, not an ADM/GDZ standard
             and not something taken from any supplied document.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

# =====================================================================================
# READ side - existing devices (from supplied documentation)
# =====================================================================================

# --- MPR-53CS energy analyzer (MPR-53CS_Modbus_Register_Map_EN.pdf) -------------------
# Addresses step by 2 -> 32-bit values over 2 registers. Word order is NOT stated in the map,
# and whether the value is already multiplied by the CT ratio is NOT stated either (open questions).
MPR53CS = {
    "voltage_l1": {"addr": 0, "mult": 0.1, "unit": "V", "scale": "xVT"},
    "voltage_l2": {"addr": 2, "mult": 0.1, "unit": "V", "scale": "xVT"},
    "voltage_l3": {"addr": 4, "mult": 0.1, "unit": "V", "scale": "xVT"},
    "current_l1_a": {"addr": 6, "mult": 0.001, "unit": "A", "scale": "xCT"},
    "current_l2_a": {"addr": 8, "mult": 0.001, "unit": "A", "scale": "xCT"},
    "current_l3_a": {"addr": 10, "mult": 0.001, "unit": "A", "scale": "xCT"},
    "current_n_a": {"addr": 12, "mult": 0.001, "unit": "A", "scale": "xCT"},
    "cosphi_l1": {"addr": 38, "mult": 0.001, "unit": "-", "signed": True},
    "frequency_hz": {"addr": 58, "mult": 0.01, "unit": "Hz"},
    "current_thd_l1": {"addr": 78, "mult": 0.1, "unit": "%"},
    "current_thd_l2": {"addr": 80, "mult": 0.1, "unit": "%"},
    "current_thd_l3": {"addr": 82, "mult": 0.1, "unit": "%"},
    "ct_ratio": {"addr": 32769, "mult": 1, "unit": "-"},  # 0x8001, R/W setting
}


def mpr_current(raw: int, ct_ratio: int) -> float:
    """Assumes raw is secondary-referred (range (0-6000)xCT, mult 0.001). Verify on a real device."""
    return raw * 0.001 * ct_ratio


# --- ABB TVOC-2-COM (1SFC170017M0201 Rev D) -------------------------------------------
# Modbus RTU slave, RS485 2-wire, default 19200 8E1, default ID 248 = communication disabled.
TVOC2 = {
    "number_of_trips": 149,
    "diagnostics_trip": 206,
    "diagnostics_trip_detector_low": 210,
    "diagnostics_trip_detector_high": 211,
    "diagnostics_trip_relay": 212,   # manual 4.4.1.3: bit0=K4, bit1=K5, bit2=K6 (IGBT outputs)
    "sensor_status_x2": 222,
    "sensor_status_x3": 223,
    "ambient_light_warning_x2": 224,
    "ambient_light_warning_x3": 225,
    "number_of_errors": 368,
    "system_state": 1300,
    "active_dtc_1": 1301,
}


def decode_tvoc_system_state(reg: int) -> dict[str, bool]:
    """Reg 1300, 4-bit field (manual 4.4.12)."""
    return {
        "trip_active": bool(reg & 0x1),
        "error_active": bool(reg & 0x2),
        "start_sequence": bool(reg & 0x4),
        "diagnostics_running": bool(reg & 0x8),
    }


def decode_trip_detectors(low: int, high: int) -> list[str]:
    """Regs 'Trip x detector low/high' -> detector names like 'X1:3' (manual 4.4.1.1-2)."""
    names_low = [f"X1:{i}" for i in range(1, 11)] + [f"X2:{i}" for i in range(1, 6)]
    names_high = [f"X2:{i}" for i in range(6, 11)] + [f"X3:{i}" for i in range(1, 11)]
    hits = [n for b, n in enumerate(names_low) if low != 0xFFFF and low >> b & 1]
    hits += [n for b, n in enumerate(names_high) if high != 0xFFFF and high >> b & 1]
    return hits


def decode_trip_relays(reg: int) -> list[str]:
    """Reg 212 / 'Trip x relay' -> which IGBT outputs operated (manual 4.4.1.3)."""
    return [n for b, n in enumerate(("K4", "K5", "K6")) if reg not in (0xFFFF,) and reg >> b & 1]


def arc_detected_without_trip(detector_low: int, detector_high: int, relay: int) -> bool:
    """[ASSUMPTION] Arc mode 1: detectors named an arc, no output relay operated.

    No mode register exists in the manual, so this is the closest observable. Regs 210-212 read
    0x0000 when there is no active trip record, so the detector words must be non-zero for this
    to mean anything. Verify on a real device.
    """
    if 0xFFFF in (detector_low, detector_high, relay):
        return False
    return bool(detector_low or detector_high) and not decode_trip_relays(relay)


def decode_tvoc_datetime(days_since_1970: int, hhmm: int, ss: int = 0) -> dt.datetime:
    return (dt.datetime(1970, 1, 1) + dt.timedelta(days=days_since_1970)).replace(
        hour=hhmm >> 8, minute=hhmm & 0xFF, second=ss)


# =====================================================================================
# WRITE side - OUR PROPOSED SCADA output block (not an existing ADM/GDZ map)
# =====================================================================================

SCADA_BASE = 1000          # first holding register of module index 0
SCADA_BLOCK_SIZE = 32      # 100 modules -> 3200 registers, one Modbus TCP server
NA_UNSIGNED = 0xFFFF       # "value not available"
NA_SIGNED = 0x8000         # "value not available" for signed fields (-32768)

ALARM_BITS = {"ARC_TRIP": 0, "ARC_SYSTEM_ERROR": 1, "ABS_TEMP_CRITICAL": 2, "OVERLOAD_RULE": 3,
              "CONDENSATION_RULE": 4, "SENSOR_FAULT": 5, "ARC_LIGHT_WARNING": 6,
              "ARC_DETECTED_NO_TRIP": 12}
ALARM_BIT_WATCH, ALARM_BIT_WARNING, ALARM_BIT_CRITICAL = 7, 8, 9
ALARM_BIT_ML_UNAVAILABLE, ALARM_BIT_BASELINE_INVALID = 10, 11

# bit = 1 means the channel is present and healthy
SENSOR_HEALTH_BITS = ["temp_l1_c", "temp_l2_c", "temp_l3_c", "temp_internal_c", "temp_ambient_c",
                      "humidity_internal_pct", "current", "pd", "arc"]

ARC_STATUS_OK, ARC_STATUS_LIGHT, ARC_STATUS_ERROR, ARC_STATUS_TRIP = 0, 1, 2, 3
ARC_STATUS_DETECTED_NO_TRIP = 4   # arc seen, trip circuit did not fire


@dataclass(frozen=True)
class Register:
    offset: int
    name: str
    scale: float
    signed: bool
    description: str


SCADA_REGISTERS: tuple[Register, ...] = (
    Register(0, "status_code", 1, False, "0=NORMAL 1=WATCH 2=WARNING 3=CRITICAL"),
    Register(1, "risk_score", 1, False, "0-100"),
    Register(2, "health_score", 1, False, "0-100"),
    Register(3, "confidence_pct", 100, False, "0-100 %"),
    Register(4, "condition_code", 1, False, "suspected condition, see CONDITION_CODES"),
    Register(5, "top_reason_code", 1, False, "highest-contribution reason, see REASON_CODES"),
    Register(6, "alarm_bitmap", 1, False, "see ALARM_BITS"),
    Register(7, "sensor_health_bitmap", 1, False, "see SENSOR_HEALTH_BITS, 1=healthy"),
    Register(8, "temp_max_c", 10, True, "0.1 degC, hottest monitored connection"),
    Register(9, "temp_l1_c", 10, True, "0.1 degC"),
    Register(10, "temp_l2_c", 10, True, "0.1 degC"),
    Register(11, "temp_l3_c", 10, True, "0.1 degC"),
    Register(12, "temp_internal_c", 10, True, "0.1 degC, cabinet air"),
    Register(13, "temp_ambient_c", 10, True, "0.1 degC, room"),
    Register(14, "humidity_pct", 10, False, "0.1 %RH"),
    Register(15, "dew_margin_c", 10, True, "0.1 degC, surface minus dew point"),
    Register(16, "current_l1_a", 10, False, "0.1 A"),
    Register(17, "current_l2_a", 10, False, "0.1 A"),
    Register(18, "current_l3_a", 10, False, "0.1 A"),
    Register(19, "current_n_a", 10, False, "0.1 A"),
    Register(20, "current_max_pct", 100, False, "% of rated current"),
    Register(21, "thermal_image_pct", 100, False, "% of rated thermal state"),
    Register(22, "pd_rate_per_min", 1, False, "PD pulses/min, NA if no PD channel"),
    Register(23, "pd_peak_mv", 1, False, "mV, NA if no PD channel"),
    Register(24, "arc_status", 1, False, "0=ok 1=light-warning 2=system-error 3=trip 4=detected-no-trip"),
    Register(25, "time_to_critical_h", 10, False, "0.1 h trend extrapolation, NA if not trending"),
    Register(26, "data_completeness_pct", 100, False, "%"),
    Register(27, "reason_2_code", 1, False, "second reason, 0 if none"),
    Register(28, "reason_3_code", 1, False, "third reason, 0 if none"),
    Register(29, "timestamp_high", 1, False, "unix seconds, high word"),
    Register(30, "timestamp_low", 1, False, "unix seconds, low word"),
    Register(31, "heartbeat", 1, False, "increments every update; stale value = engine stopped"),
)


def module_base_address(module_index: int) -> int:
    return SCADA_BASE + module_index * SCADA_BLOCK_SIZE


def _encode(value: float | None, reg: Register) -> int:
    if value is None:
        return NA_SIGNED if reg.signed else NA_UNSIGNED
    raw = int(round(value * reg.scale))
    if reg.signed:
        return raw & 0xFFFF
    return max(0, min(raw, 0xFFFE))


def _alarm_bitmap(payload: dict[str, Any]) -> int:
    bits = 0
    for rule in payload.get("hard_rules", []):
        if rule in ALARM_BITS:
            bits |= 1 << ALARM_BITS[rule]
    status_code = payload.get("status_code", 0)
    for level, bit in ((1, ALARM_BIT_WATCH), (2, ALARM_BIT_WARNING), (3, ALARM_BIT_CRITICAL)):
        if status_code >= level:
            bits |= 1 << bit
    dq = payload.get("data_quality", {})
    if not dq.get("ml_available", True):
        bits |= 1 << ALARM_BIT_ML_UNAVAILABLE
    if not dq.get("baseline_valid", True):
        bits |= 1 << ALARM_BIT_BASELINE_INVALID
    return bits


def _sensor_health_bitmap(payload: dict[str, Any]) -> int:
    dq = payload.get("data_quality", {})
    faulty = set(dq.get("faulty_channels", [])) | set(dq.get("missing_channels", []))
    summary = payload.get("sensor_summary", {})
    bits = 0
    for i, name in enumerate(SENSOR_HEALTH_BITS):
        if name in ("current", "pd", "arc"):
            healthy = summary.get({"current": "current", "pd": "partial_discharge", "arc": "arc"}[name],
                                  {}).get("status") in ("ok", "partial")
        else:
            healthy = name not in faulty
        if healthy:
            bits |= 1 << i
    return bits


def _arc_status(payload: dict[str, Any]) -> int:
    arc = payload.get("sensor_summary", {}).get("arc", {})
    if arc.get("trip_active"):
        return ARC_STATUS_TRIP
    if arc.get("detected_no_trip"):
        return ARC_STATUS_DETECTED_NO_TRIP
    if arc.get("system_error"):
        return ARC_STATUS_ERROR
    if arc.get("light_warning"):
        return ARC_STATUS_LIGHT
    return ARC_STATUS_OK


def scada_values(payload: dict[str, Any], heartbeat: int = 0) -> dict[str, float | None]:
    """Flatten an inference payload into the named values of the proposed block."""
    from .reasons import CONDITION_CODES, REASON_CODES

    s = payload.get("sensor_summary", {})
    temp, cur, hum, pdis = s.get("temperature", {}), s.get("current", {}), s.get("humidity", {}), s.get("partial_discharge", {})
    reasons = payload.get("reasons", [])
    codes = [REASON_CODES.get(r["code"], 0) for r in reasons[:3]] + [0, 0, 0]
    epoch = int(dt.datetime.fromisoformat(payload["timestamp"].replace("Z", "+00:00")).timestamp())
    kv = payload.get("key_values", {})
    return {
        "status_code": payload.get("status_code", 0),
        "risk_score": payload.get("risk_score", 0),
        "health_score": payload.get("health_score", 0),
        "confidence_pct": payload.get("confidence", 0.0),
        "condition_code": CONDITION_CODES.get((payload.get("suspected_condition") or {}).get("code"), 0),
        "top_reason_code": codes[0],
        "alarm_bitmap": _alarm_bitmap(payload),
        "sensor_health_bitmap": _sensor_health_bitmap(payload),
        "temp_max_c": temp.get("max_c"), "temp_l1_c": temp.get("l1_c"), "temp_l2_c": temp.get("l2_c"),
        "temp_l3_c": temp.get("l3_c"), "temp_internal_c": temp.get("internal_c"),
        "temp_ambient_c": temp.get("ambient_c"),
        "humidity_pct": hum.get("rh_pct"), "dew_margin_c": hum.get("dew_margin_c"),
        "current_l1_a": cur.get("l1_a"), "current_l2_a": cur.get("l2_a"), "current_l3_a": cur.get("l3_a"),
        "current_n_a": cur.get("n_a"), "current_max_pct": cur.get("max_pu"),
        "thermal_image_pct": kv.get("thermal_image"),
        "pd_rate_per_min": pdis.get("rate_per_min"), "pd_peak_mv": pdis.get("peak_mv"),
        "arc_status": _arc_status(payload),
        "time_to_critical_h": payload.get("time_to_critical_h"),
        "data_completeness_pct": payload.get("data_quality", {}).get("completeness"),
        "reason_2_code": codes[1], "reason_3_code": codes[2],
        "timestamp_high": epoch >> 16, "timestamp_low": epoch & 0xFFFF,
        "heartbeat": heartbeat & 0xFFFF,
    }


def build_scada_block(payload: dict[str, Any], heartbeat: int = 0) -> list[int]:
    """Encode one inference payload into SCADA_BLOCK_SIZE holding registers."""
    values = scada_values(payload, heartbeat)
    return [_encode(values.get(reg.name), reg) for reg in SCADA_REGISTERS]
