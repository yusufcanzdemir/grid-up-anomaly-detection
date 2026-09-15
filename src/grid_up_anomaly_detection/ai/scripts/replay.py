"""Replay a generated scenario into the running API as if a real panel were sending readings.

    python ai/scripts/replay.py --scenario loose_connection --speed 600

`speed` is the time-acceleration factor (600 = one simulated minute per 0.1 s). `stride` feeds every
Nth minute, which is safe because every feature uses time windows rather than sample counts.
The engine buffer is primed with the preceding 26 h first, so the replay can start just before onset.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import pandas as pd

from grid_up_anomaly_detection.ai.config import SYNTH_DIR
from grid_up_anomaly_detection.ai.observability import format_tick
from grid_up_anomaly_detection.ai.schema import CANONICAL_COLUMNS


def post(url: str, body: dict[str, Any] | None = None, timeout: float = 30.0) -> dict[str, Any]:
    data = json.dumps(body or {}, default=str).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


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
    print(f"speed x{args.speed:g}, stride {args.stride} min\n")

    # urlencode matters: a raw "+00:00" in a query string decodes to a space on the server
    query = urllib.parse.urlencode({"scenario": args.scenario, "until": begin.isoformat(),
                                    "stride": args.stride})   # prime at the cadence we will stream at
    primed = post(f"{args.api}/modules/{args.module_id}/prime?{query}", timeout=120)
    print(f"primed engine buffer with {primed['rows']} historical readings\n")

    rows = df[df["timestamp"] >= begin].iloc[::args.stride]
    if args.max_samples:
        rows = rows.iloc[:args.max_samples]
    delay = 60.0 * args.stride / args.speed

    seen_reasons: dict[str, int] = {}
    worst = {"risk_score": -1}
    first_alarm = None
    detect_level = {"WATCH": 1, "WARNING": 2, "CRITICAL": 3}.get(meta.get("detect_level", "WARNING"), 2)
    last_status = None

    for record in rows.to_dict("records"):
        started = time.perf_counter()
        record["module_id"] = args.module_id      # the primed buffer belongs to this id
        payload = post(f"{args.api}/ingest", clean(record))
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
                         f"  cd ai && poetry run uvicorn grid_up_anomaly_detection.ai.service.app:app --port 8000")
