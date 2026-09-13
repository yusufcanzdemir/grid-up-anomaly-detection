"""Smoke tests for the FastAPI prototype: the endpoints the dashboard actually calls."""
from __future__ import annotations

import pandas as pd
import pytest

pytest.importorskip("fastapi", reason="API prototype needs the `api` extra")

from fastapi.testclient import TestClient  # noqa: E402

from gridup_ai.config import SYNTH_DIR  # noqa: E402
from gridup_ai.modbus_maps import SCADA_BLOCK_SIZE  # noqa: E402
from gridup_ai.observability import format_tick  # noqa: E402
from gridup_ai.service.app import create_app  # noqa: E402
from gridup_ai.simulator import Scenario, simulate  # noqa: E402

MODULE = "TEST-M1"


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(scope="module")
def readings() -> list[dict]:
    df = simulate(Scenario("n", "normal", days=1, onset_day=None), seed=17, module_id=MODULE,
                  panel_id="TEST-P1")
    rows = df.iloc[-40:].to_dict("records")
    return [{k: (None if isinstance(v, float) and pd.isna(v) else v) for k, v in r.items()
             if k in {"timestamp", "module_id", "panel_id", "site_id", "profile"} or "_" in k}
            for r in rows]


def test_health_reports_engine_state(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert "ml_available" in body and "baselines_loaded" in body


def test_ingest_returns_the_frozen_payload(client, readings):
    payload = None
    for reading in readings:
        reading["timestamp"] = str(reading["timestamp"])
        payload = client.post("/ingest", json=reading).json()
    assert payload["module_id"] == MODULE
    assert payload["status"] in ("NORMAL", "WATCH", "WARNING", "CRITICAL")
    assert 0 <= payload["risk_score"] <= 100
    assert "sensor_summary" in payload and "confidence" in payload
    assert format_tick(payload).startswith(payload["timestamp"][11:19])


def test_module_endpoints(client, readings):
    assert MODULE in [m["module_id"] for m in client.get("/modules").json()["modules"]]
    assert client.get(f"/modules/{MODULE}").json()["module_id"] == MODULE
    assert client.get(f"/modules/{MODULE}/latest").json()["module_id"] == MODULE
    points = client.get(f"/modules/{MODULE}/history").json()["points"]
    assert len(points) == len(readings)
    assert {"timestamp", "risk_score", "status"} <= set(points[0])


def test_unknown_module_is_404(client):
    assert client.get("/modules/NOPE/latest").status_code == 404


@pytest.mark.skipif(not (SYNTH_DIR / "scenarios" / "loose_connection.csv.gz").exists(),
                    reason="synthetic data not generated")
def test_prime_and_replay_plumbing(client):
    """The replay driver depends on these two routes existing - a missing route broke a live demo."""
    primed = client.post("/modules/DEMO-PRIME/prime", params={"scenario": "loose_connection"})
    assert primed.status_code == 200
    assert primed.json()["rows"] > 0 and primed.json()["buffer_rows"] > 0

    job = client.post("/simulate/loose_connection",
                      params={"module_id": "DEMO-PRIME", "speed": 1e6, "stride": 60}).json()
    assert job["state"] == "running" and job["total"] > 0
    assert client.delete(f"/simulate/{job['job_id']}").json()["state"] in ("stopping", "finished")
    assert any(j["job_id"] == job["job_id"] for j in client.get("/simulate").json()["jobs"])


@pytest.mark.skipif(not (SYNTH_DIR / "scenarios" / "loose_connection.csv.gz").exists(),
                    reason="synthetic data not generated")
def test_prime_accepts_an_explicit_until_timestamp(client):
    """Both tz-aware and naive timestamps must work; a URL can swallow the '+00:00' offset."""
    for until in ("2026-09-08T18:00:00+00:00", "2026-09-08T18:00:00"):
        r = client.post("/modules/DEMO-UNTIL/prime",
                        params={"scenario": "loose_connection", "until": until})
        assert r.status_code == 200, r.text
        assert r.json()["rows"] > 0
    assert client.post("/modules/DEMO-UNTIL/prime",
                       params={"scenario": "loose_connection", "until": "not-a-date"}).status_code == 400


def test_unknown_scenario_is_404(client):
    assert client.post("/modules/X/prime", params={"scenario": "does_not_exist"}).status_code == 404


def test_events_and_scada(client):
    assert "events" in client.get("/events").json()
    scada = client.get(f"/scada/{MODULE}").json()
    assert len(scada["raw"]) == SCADA_BLOCK_SIZE
    assert scada["base_address"] == 1000
