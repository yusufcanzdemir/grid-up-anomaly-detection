"""Replay a generated scenario into the running API as if a real panel were sending readings.

    python ai/scripts/replay.py --scenario loose_connection --speed 600

`speed` is the time-acceleration factor (600 = one simulated minute per 0.1 s). `stride` feeds every
Nth minute, which is safe because every feature uses time windows rather than sample counts.
The engine buffer is primed with the preceding 26 h first, so the replay can start just before onset.

`--via mqtt` publishes the same scenario rows to the telemetry topic instead of calling /ingest, so the
full demo path is exercised: scenario -> MQTT -> mqtt_to_db.py -> /ingest -> RiskEngine.update().
The payload is then read back from /modules/{id}/latest. Priming stays an HTTP call: it is buffer
history, not live telemetry.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

import pandas as pd

from grid_up_anomaly_detection.ai.config import SYNTH_DIR
from grid_up_anomaly_detection.ai.observability import format_tick
from grid_up_anomaly_detection.ai.schema import CANONICAL_COLUMNS


def post(url: str, body: dict[str, Any] | None = None, timeout: float = 30.0) -> dict[str, Any]:
    data = json.dumps(body or {}, default=str).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def get(url: str, timeout: float = 30.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read())


def mqtt_sender(api: str, host: str | None, port: int | None,
                timeout: float = 30.0) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Publish one reading to the broker and wait until the backend has scored it."""
    import paho.mqtt.client as mqtt

    from grid_up_anomaly_detection.simulate_mqtt import MQTT_BROKER, MQTT_PORT, MQTT_TOPIC

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(host or MQTT_BROKER, port or MQTT_PORT, 60)
    client.loop_start()

    def send(reading: dict[str, Any]) -> dict[str, Any]:
        client.publish(MQTT_TOPIC, json.dumps(reading, default=str), qos=1).wait_for_publish(timeout)
        want = pd.Timestamp(reading["timestamp"])
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                payload = get(f"{api}/modules/{reading['module_id']}/latest")
                if pd.Timestamp(payload["timestamp"]) == want:
                    return payload
            except urllib.error.HTTPError as exc:
                if exc.code != 404:          # 404 = backend has not scored this module yet
                    raise
            time.sleep(0.05)
        raise SystemExit(f"no inference for {want} within {timeout:.0f} s: is mqtt_to_db.py running "
                         f"and pointed at {api}?")

    return send


def clean(record: dict[str, Any]) -> dict[str, Any]:
    """Canonical fields only, NaN -> None (JSON has no NaN)."""
    out = {}
    for key in CANONICAL_COLUMNS:
        value = record.get(key)
        out[key] = None if isinstance(value, float) and pd.isna(value) else value
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--module-id", default="PANEL-03")
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--speed", type=float, default=600, help="time acceleration factor")
    ap.add_argument("--stride", type=int, default=5, help="feed every Nth minute")
    ap.add_argument("--hours-before-onset", type=float, default=6.0)
    ap.add_argument("--max-samples", type=int, default=0, help="0 = whole scenario")
    ap.add_argument("--via", choices=("http", "mqtt"), default="http",
                    help="http: POST /ingest directly; mqtt: publish to the broker (needs mqtt_to_db.py running)")
    ap.add_argument("--mqtt-host", default=None, help="default: simulate_mqtt.MQTT_BROKER")
    ap.add_argument("--mqtt-port", type=int, default=None, help="default: simulate_mqtt.MQTT_PORT")
    args = ap.parse_args()

    meta_all = json.loads((SYNTH_DIR / "meta.json").read_text())
    meta = next((m for m in meta_all.values() if m["scenario"] == args.scenario), None)
    path = SYNTH_DIR / "scenarios" / f"{args.scenario}.csv.gz"
    if meta is None or not path.exists():
        raise SystemExit(f"unknown scenario '{args.scenario}'. available: "
                         f"{sorted(p.stem.replace('.csv', '') for p in (SYNTH_DIR / 'scenarios').glob('*.csv.gz'))}")

    df = pd.read_csv(path, parse_dates=["timestamp"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    onset = pd.Timestamp(meta["onset"]) if meta["onset"] else None
    failure = pd.Timestamp(meta["failure"]) if meta["failure"] else None
    begin = (onset - pd.Timedelta(hours=args.hours_before_onset)) if onset is not None else df["timestamp"].iloc[26 * 60]

    print(f"scenario           : {args.scenario}  ({meta['profile']})")
    print(f"module             : {args.module_id}")
    print(f"onset / failure    : {onset} / {failure}")
    print(f"expected condition : {meta['expected_condition']}  (alarm at {meta.get('detect_level', 'WARNING')})")
    print(f"expected reasons   : {', '.join(meta.get('expected_reasons') or []) or '-'}")
    print(f"speed x{args.speed:g}, stride {args.stride} min, via {args.via}\n")

    # urlencode matters: a raw "+00:00" in a query string decodes to a space on the server
    query = urllib.parse.urlencode({"scenario": args.scenario, "until": begin.isoformat(),
                                    "stride": args.stride})   # prime at the cadence we will stream at
    primed = post(f"{args.api}/modules/{args.module_id}/prime?{query}", timeout=120)
    print(f"primed engine buffer with {primed['rows']} historical readings\n")

    rows = df[df["timestamp"] >= begin].iloc[::args.stride]
    if args.max_samples:
        rows = rows.iloc[:args.max_samples]
    delay = 60.0 * args.stride / args.speed
    if args.via == "mqtt":
        send = mqtt_sender(args.api, args.mqtt_host, args.mqtt_port)
    else:
        def send(reading: dict[str, Any]) -> dict[str, Any]:
            return post(f"{args.api}/ingest", reading)

    seen_reasons: dict[str, int] = {}
    worst = {"risk_score": -1}
    first_alarm = None
    detect_level = {"WATCH": 1, "WARNING": 2, "CRITICAL": 3}.get(meta.get("detect_level", "WARNING"), 2)
    last_status = None

    for record in rows.to_dict("records"):
        started = time.perf_counter()
        record["module_id"] = args.module_id      # the primed buffer belongs to this id
        payload = send(clean(record))
        if payload["status"] != last_status or payload["reasons"]:
            print(format_tick(payload))
            last_status = payload["status"]
        for reason in payload["reasons"]:
            seen_reasons[reason["code"]] = seen_reasons.get(reason["code"], 0) + 1
        if payload["risk_score"] > worst["risk_score"]:
            worst = payload
        if first_alarm is None and payload["status_code"] >= detect_level:
            first_alarm = payload
        time.sleep(max(0.0, delay - (time.perf_counter() - started)))

    print("\n--- replay summary ---")
    print(f"worst status       : {worst['status']} (risk {worst['risk_score']}, health {worst['health_score']})")
    if first_alarm is not None:
        alarm_at = pd.Timestamp(first_alarm["timestamp"])
        # the condition at the alarm is what matters; at peak risk a degradation scenario has
        # usually already ended in the arc trip it was leading to
        print(f"condition at alarm : {first_alarm['suspected_condition']['code']} "
              f"(expected {meta['expected_condition']})")
        print(f"condition at worst : {worst['suspected_condition']['code']}")
        print(f"first alarm        : {alarm_at} -> {first_alarm['status']}")
        if failure is not None:
            print(f"lead time          : {(failure - alarm_at).total_seconds() / 3600:.1f} h before failure")
    else:
        print(f"first alarm        : none (expected max status {meta.get('expected_max_status')})")
    expected = set(meta.get("expected_reasons") or [])
    observed = set(seen_reasons)
    print(f"reason codes seen  : {', '.join(sorted(observed)) or '-'}")
    if expected:
        print(f"expected reasons   : {'MATCHED' if expected & observed else 'MISSING'} "
              f"({', '.join(sorted(expected & observed)) or 'none of ' + ', '.join(sorted(expected))})")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:      # subclass of URLError, so it must be caught first
        raise SystemExit(f"API returned {exc.code} for {exc.url}\n{exc.read().decode()[:500]}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"cannot reach the API ({exc.reason}). Start it with:\n"
                         f"  poetry run uvicorn grid_up_anomaly_detection.ai.service.app:app --port 8000")
