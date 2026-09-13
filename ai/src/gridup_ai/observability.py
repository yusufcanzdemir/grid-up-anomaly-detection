"""One-line rendering of an inference payload, shared by the API log and the replay driver.

    12:14:00 PANEL-03 risk= 24 NORMAL
    12:17:00 PANEL-03 risk= 67 WARNING  CONNECTION_HEATING (thermal_model)  LOOSE_CONNECTION
"""
from __future__ import annotations

from typing import Any

STATUS_WIDTH = 8


def top_reason(payload: dict[str, Any]) -> dict[str, Any] | None:
    reasons = payload.get("reasons") or []
    return reasons[0] if reasons else None


def format_tick(payload: dict[str, Any], with_condition: bool = True) -> str:
    ts = str(payload.get("timestamp", ""))
    clock = ts[11:19] if len(ts) >= 19 else ts
    line = (f"{clock} {payload.get('module_id', '?'):<12} "
            f"risk={payload.get('risk_score', 0):>3} {payload.get('status', '?'):<{STATUS_WIDTH}}")
    reason = top_reason(payload)
    if reason:
        line += f" {reason['code']} ({reason['source']})"
    condition = (payload.get("suspected_condition") or {}).get("code")
    if with_condition and condition and condition != "NONE":
        line += f"  -> {condition}"
    return line
