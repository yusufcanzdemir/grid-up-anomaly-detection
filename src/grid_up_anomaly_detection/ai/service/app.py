"""FastAPI wrapper around the risk engine.

Prototype scope on purpose: in-memory state, no auth, no broker, single process.

    poetry run uvicorn grid_up_anomaly_detection.ai.service.app:app --reload --port 8000     (from ai/, needs the `api` extra)
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

import pandas as pd
from fastapi import Body, FastAPI, HTTPException, Query
from pydantic import BaseModel

from grid_up_anomaly_detection.ai.baseline import load_baselines
from grid_up_anomaly_detection.ai.config import MODELS_DIR, SYNTH_DIR, load_config
from grid_up_anomaly_detection.ai.engine import RiskEngine
from grid_up_anomaly_detection.ai.ml import MLDetector
from grid_up_anomaly_detection.ai.modbus_maps import SCADA_BLOCK_SIZE, SCADA_REGISTERS, build_scada_block, module_base_address
from grid_up_anomaly_detection.ai.observability import format_tick
from grid_up_anomaly_detection.ai.schema import CANONICAL_COLUMNS

from .store import Store

log = logging.getLogger("gridup.api")
PRIME_HOURS = 26  # engine feature windows need up to ~26 h of context


def parse_utc(value: str) -> pd.Timestamp:
    """Parse a query/body timestamp into UTC, with a 400 instead of a 500 on malformed input."""
    try:
        ts = pd.Timestamp(value)
    except ValueError as exc:
        raise HTTPException(400, f"invalid timestamp '{value}': {exc}") from exc
    if ts.tzinfo is None:                       # tolerate naive input (and '+00:00' eaten by a URL)
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


class Reading(BaseModel):
    """One canonical sensor reading. Every channel is optional except the identity fields."""
    module_id: str
    timestamp: str
    panel_id: str | None = None
    site_id: str | None = None
    profile: str | None = "LV_PANEL"
    current_l1_a: float | None = None
    current_l2_a: float | None = None
    current_l3_a: float | None = None
    current_n_a: float | None = None
    current_thd_pct: float | None = None
    temp_l1_c: float | None = None
    temp_l2_c: float | None = None
    temp_l3_c: float | None = None
    temp_internal_c: float | None = None
    humidity_internal_pct: float | None = None
    temp_ambient_c: float | None = None
    pd_count_per_min: float | None = None
    pd_peak_mv: float | None = None
    arc_trip_active: float | None = 0
    arc_trip_count: float | None = 0
    arc_system_error: float | None = 0
    arc_light_warning: float | None = 0

    def to_canonical(self) -> dict[str, Any]:
        return {c: getattr(self, c, None) for c in CANONICAL_COLUMNS}


class EngineService:
    """Owns the engine, the store and the replay jobs. All engine access is serialised."""

    def __init__(self) -> None:
        self.cfg = load_config()
        self.started_at = time.time()
        baselines = load_baselines(MODELS_DIR / "baselines.json") if (MODELS_DIR / "baselines.json").exists() else {}
        self.ml = MLDetector.load(MODELS_DIR / "iforest.joblib")
        self.engine = RiskEngine(self.cfg, baselines, self.ml)
        self.store = Store()
        self.jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._heartbeat = 0
        log.info("engine ready: %d baselines, ML=%s", len(baselines), self.ml is not None)

    # ---------------- inference ----------------
    def ingest(self, reading: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            payload = self.engine.update(reading)
            self._heartbeat += 1
            event = self.store.record(payload)
        log.info("%s", format_tick(payload))
        if event and event["status_code"] >= 2:
            log.warning("ALARM %s %s -> %s (%s)", event["module_id"], event["previous_status"],
                        event["status"], event["condition"])
                        
            try:
                from grid_up_anomaly_detection.communication.telegram.bot import send_telegram_alert
                from grid_up_anomaly_detection.communication.telegram.listener import ACTIVE_ALARMS
                from grid_up_anomaly_detection.models import Alarm, AlarmStatus

                alarm = Alarm(
                    id=int(time.time()),
                    panel=payload.get("panel_id") or payload.get("module_id") or "Bilinmeyen",
                    location=payload.get("site_id") or "Ana Üretim Hattı",
                    status=AlarmStatus.CRITICAL,  # İş akışı durumu (workflow_state)
                    ai_status=payload.get("status", "Bilinmiyor"),
                    suspected_condition=(payload.get("suspected_condition") or {}).get("message", (payload.get("suspected_condition") or {}).get("code", "")),
                    reasons=[r.get("message", r.get("code", "")) for r in payload.get("reasons", [])]
                )
                
                result = send_telegram_alert(alarm)
                if result and result.get("message_id"):
                    ACTIVE_ALARMS[result.get("message_id")] = alarm
                    log.info("Telegram bildirimi başarıyla gönderildi ve aktif alarmlara eklendi.")
            except Exception as e:
                log.error(f"Telegram bildirimi gönderilemedi: {e}")
                
        return payload

    def heartbeat(self) -> int:
        return self._heartbeat

    # ---------------- scenario support ----------------
    def scenario_meta(self) -> dict[str, Any]:
        path = SYNTH_DIR / "meta.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text())

    def scenario_frame(self, scenario: str) -> pd.DataFrame:
        path = SYNTH_DIR / "scenarios" / f"{scenario}.csv.gz"
        if not path.exists():
            raise HTTPException(404, f"scenario '{scenario}' not generated; run scripts/generate_synthetic.py")
        df = pd.read_csv(path, parse_dates=["timestamp"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df

    def prime(self, scenario: str, module_id: str, until: str | None = None, hours: float = PRIME_HOURS,
              stride: int = 1) -> int:
        """Fill a module's rolling buffer with history *without* scoring it, so a replay can start
        mid-scenario. Also aliases the scenario's fitted baseline onto the demo module id.

        `stride` must match the cadence the caller will stream at: a buffer that mixes 1-minute
        history with 15-minute live samples makes the window statistics misjudge the cadence.
        """
        df = self.scenario_frame(scenario)
        source_id = str(df["module_id"].iloc[0])
        end = parse_utc(until) if until else df["timestamp"].iloc[0] + pd.Timedelta(hours=hours)
        window = df[(df["timestamp"] <= end) & (df["timestamp"] > end - pd.Timedelta(hours=hours))].copy()
        window = window.iloc[::stride] if stride > 1 else window
        window["module_id"] = module_id
        with self._lock:
            if source_id in self.engine.baselines and module_id not in self.engine.baselines:
                self.engine.baselines[module_id] = self.engine.baselines[source_id]
            self.engine.buffers[module_id] = window[CANONICAL_COLUMNS].reset_index(drop=True)
            self.engine.state.pop(module_id, None)
        return len(window)

    def start_replay(self, scenario: str, module_id: str, speed: float, stride: int,
                     start: str | None) -> dict[str, Any]:
        df = self.scenario_frame(scenario)
        begin = parse_utc(start) if start else df["timestamp"].iloc[0] + pd.Timedelta(hours=PRIME_HOURS)
        self.prime(scenario, module_id, until=str(begin), stride=stride)
        rows = df[df["timestamp"] > begin].iloc[::stride]
        job_id = f"{scenario}:{module_id}"
        job = {"job_id": job_id, "scenario": scenario, "module_id": module_id, "speed": speed,
               "stride": stride, "total": len(rows), "sent": 0, "state": "running"}
        self.jobs[job_id] = job

        def run() -> None:
            delay = 60.0 * stride / max(speed, 1e-6)
            for record in rows.to_dict("records"):
                if job["state"] != "running":
                    break
                record["module_id"] = module_id
                try:
                    self.ingest(record)
                except Exception:                      # a demo must not die on one bad sample
                    log.exception("replay ingest failed")
                job["sent"] += 1
                time.sleep(delay)
            job["state"] = "stopped" if job["state"] == "stopping" else "finished"

        threading.Thread(target=run, name=f"replay-{job_id}", daemon=True).start()
        return job


def create_app() -> FastAPI:
    svc = EngineService()
    app = FastAPI(title="Grid Up - panel anomaly early warning", version="1.0",
                  description="Inference API for the panel/cell anomaly early-warning system.")
    app.state.svc = svc

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "uptime_s": round(time.time() - svc.started_at, 1),
            "modules": len(svc.store.module_ids()),
            "baselines_loaded": len(svc.engine.baselines),
            "ml_available": svc.ml is not None,
            "readings_processed": svc.heartbeat(),
            "scenarios": sorted(p.stem.replace(".csv", "") for p in (SYNTH_DIR / "scenarios").glob("*.csv.gz")),
        }

    @app.get("/modules")
    def modules() -> dict[str, Any]:
        return {"modules": svc.store.summaries()}

    @app.get("/modules/{module_id}")
    def module_detail(module_id: str) -> dict[str, Any]:
        payload = svc.store.latest(module_id)
        if payload is None:
            raise HTTPException(404, f"unknown module '{module_id}'")
        baseline = svc.engine.baselines.get(module_id)
        return {
            "module_id": module_id,
            "panel_id": payload.get("panel_id"),
            "latest": payload,
            "baseline": None if baseline is None else {
                "valid": baseline.valid, "rated_a": baseline.rated_a,
                "lug_rise_at_rated_k": {p: round(f.a, 2) for p, f in baseline.lug.items() if f},
                "lug_tau_min": {p: f.tau for p, f in baseline.lug.items() if f},
                "lug_r2": {p: round(f.r2, 3) for p, f in baseline.lug.items() if f},
            },
            "buffer_rows": len(svc.engine.buffers.get(module_id, [])),
        }

    @app.get("/modules/{module_id}/latest")
    def latest(module_id: str) -> dict[str, Any]:
        payload = svc.store.latest(module_id)
        if payload is None:
            raise HTTPException(404, f"unknown module '{module_id}'")
        return payload

    @app.get("/modules/{module_id}/history")
    def history(module_id: str, max_points: int = Query(500, ge=1, le=5000)) -> dict[str, Any]:
        if svc.store.latest(module_id) is None:
            raise HTTPException(404, f"unknown module '{module_id}'")
        return {"module_id": module_id, "points": svc.store.history(module_id, max_points)}

    @app.post("/modules/{module_id}/prime")
    def prime(module_id: str, scenario: str, until: str | None = None,
              hours: float = Query(PRIME_HOURS, gt=0), stride: int = Query(1, ge=1)) -> dict[str, Any]:
        """Load history into a module's rolling buffer *without* scoring it.

        Demo helper: it lets a replay start just before a fault onset while the engine still has the
        ~26 h of context its time-window features need.
        """
        rows = svc.prime(scenario, module_id, until, hours, stride)
        return {"module_id": module_id, "scenario": scenario, "until": until, "rows": rows,
                "buffer_rows": len(svc.engine.buffers.get(module_id, []))}

    @app.get("/events")
    def events(limit: int = Query(100, ge=1, le=500), min_status: str = "WATCH") -> dict[str, Any]:
        return {"events": svc.store.events(limit, min_status)}

    @app.post("/ingest")
    def ingest(reading: Reading) -> dict[str, Any]:
        return svc.ingest(reading.to_canonical())

    @app.post("/ingest/batch")
    def ingest_batch(readings: list[Reading] = Body(...)) -> dict[str, Any]:
        payloads = [svc.ingest(r.to_canonical()) for r in readings]
        return {"count": len(payloads), "last": payloads[-1] if payloads else None}

    @app.get("/scada/{module_id}")
    def scada(module_id: str, module_index: int = 0) -> dict[str, Any]:
        payload = svc.store.latest(module_id)
        if payload is None:
            raise HTTPException(404, f"unknown module '{module_id}'")
        registers = build_scada_block(payload, svc.heartbeat())
        base = module_base_address(module_index)
        return {
            "module_id": module_id,
            "base_address": base,
            "block_size": SCADA_BLOCK_SIZE,
            "registers": {base + r.offset: {"name": r.name, "value": registers[r.offset],
                                            "description": r.description} for r in SCADA_REGISTERS},
            "raw": registers,
        }

    @app.get("/scenarios")
    def scenarios() -> dict[str, Any]:
        meta = svc.scenario_meta()
        return {"scenarios": [
            {"scenario": m["scenario"], "profile": m["profile"], "onset": m["onset"], "failure": m["failure"],
             "expected_condition": m["expected_condition"], "expected_reasons": m.get("expected_reasons", []),
             "expected_max_status": m.get("expected_max_status"), "detect_level": m.get("detect_level")}
            for m in meta.values() if m["kind"] != "normal" or "normal_operation" in m["scenario"]]}

    @app.post("/simulate/{scenario}")
    def simulate(scenario: str, module_id: str = "PANEL-03", speed: float = Query(600, gt=0),
                 stride: int = Query(5, ge=1), start: str | None = None) -> dict[str, Any]:
        """Replay a generated scenario into the engine in the background (in-process)."""
        job_id = f"{scenario}:{module_id}"
        if svc.jobs.get(job_id, {}).get("state") == "running":
            raise HTTPException(409, f"replay '{job_id}' already running")
        return svc.start_replay(scenario, module_id, speed, stride, start)

    @app.get("/simulate")
    def simulate_jobs() -> dict[str, Any]:
        return {"jobs": list(svc.jobs.values())}

    @app.delete("/simulate/{job_id:path}")
    def stop_simulation(job_id: str) -> dict[str, Any]:
        job = svc.jobs.get(job_id)
        if job is None:
            raise HTTPException(404, f"unknown job '{job_id}'")
        if job["state"] == "running":
            job["state"] = "stopping"
        return job

    return app


logging.basicConfig(level=logging.INFO, format="%(message)s")
app = create_app()
