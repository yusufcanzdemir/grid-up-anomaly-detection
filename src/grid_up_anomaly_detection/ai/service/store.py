"""In-memory state for the prototype: last payload per module, short history, and an event log.

Deliberately not a database. Everything here is bounded and lost on restart, which is fine for a
demo; the persistence decision belongs to the backend teammate.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Iterable

STATUS_ORDER = {"NORMAL": 0, "WATCH": 1, "WARNING": 2, "CRITICAL": 3}

# what we keep per sample for charts (the full payload is kept only for the latest sample)
HISTORY_KEYS = ("timestamp", "risk_score", "health_score", "status", "status_code", "confidence")


class Store:
    def __init__(self, history_len: int = 1440, event_len: int = 500):
        self._latest: dict[str, dict[str, Any]] = {}
        self._history: dict[str, deque[dict[str, Any]]] = {}
        self._history_len = history_len
        self._events: deque[dict[str, Any]] = deque(maxlen=event_len)

    # ---------------- writes ----------------
    def record(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Store a payload; return an event dict if the status changed, else None."""
        module_id = payload["module_id"]
        previous = self._latest.get(module_id)
        self._latest[module_id] = payload
        hist = self._history.setdefault(module_id, deque(maxlen=self._history_len))
        point = {k: payload.get(k) for k in HISTORY_KEYS}
        point.update(condition=(payload.get("suspected_condition") or {}).get("code"),
                     top_reason=payload["reasons"][0]["code"] if payload.get("reasons") else None,
                     temp_max_c=payload.get("key_values", {}).get("temp_max_c"),
                     current_max_pu=payload.get("key_values", {}).get("current_max_pu"),
                     humidity_pct=payload.get("key_values", {}).get("humidity_pct"))
        hist.append(point)

        if previous is not None and previous.get("status") == payload.get("status"):
            return None
        event = {
            "timestamp": payload["timestamp"],
            "module_id": module_id,
            "panel_id": payload.get("panel_id"),
            "previous_status": previous.get("status") if previous else None,
            "status": payload["status"],
            "status_code": payload["status_code"],
            "risk_score": payload["risk_score"],
            "condition": (payload.get("suspected_condition") or {}).get("code"),
            "top_reason": payload["reasons"][0]["code"] if payload.get("reasons") else None,
            "message": payload["reasons"][0]["message"] if payload.get("reasons") else None,
            "notify": payload.get("notify"),
        }
        self._events.append(event)
        return event

    # ---------------- reads ----------------
    def module_ids(self) -> list[str]:
        return sorted(self._latest)

    def latest(self, module_id: str) -> dict[str, Any] | None:
        return self._latest.get(module_id)

    def summaries(self) -> list[dict[str, Any]]:
        out = []
        for module_id, payload in sorted(self._latest.items()):
            out.append({
                "module_id": module_id,
                "panel_id": payload.get("panel_id"),
                "timestamp": payload["timestamp"],
                "status": payload["status"],
                "status_code": payload["status_code"],
                "risk_score": payload["risk_score"],
                "health_score": payload["health_score"],
                "confidence": payload.get("confidence"),
                "condition": (payload.get("suspected_condition") or {}).get("code"),
                "top_reason": payload["reasons"][0]["code"] if payload.get("reasons") else None,
                "samples": len(self._history.get(module_id, ())),
            })
        return out

    def history(self, module_id: str, max_points: int = 500) -> list[dict[str, Any]]:
        points = list(self._history.get(module_id, ()))
        if len(points) <= max_points:
            return points
        step = len(points) // max_points + 1
        return points[::step]

    def events(self, limit: int = 100, min_status: str = "WATCH") -> list[dict[str, Any]]:
        floor = STATUS_ORDER.get(min_status.upper(), 1)
        selected: Iterable[dict[str, Any]] = (e for e in reversed(self._events) if e["status_code"] >= floor)
        return [e for _, e in zip(range(limit), selected)]
