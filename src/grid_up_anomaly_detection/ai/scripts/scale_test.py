"""Scale test: how much CPU and memory does the engine need for N modules?

Buffers are pre-filled directly (that is just data), then we measure real `engine.update()` calls -
the same code path the API uses.

    python src/grid_up_anomaly_detection/ai/scripts/scale_test.py --modules 100 --samples 10
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time

import pandas as pd

from grid_up_anomaly_detection.ai.baseline import load_baselines
from grid_up_anomaly_detection.ai.config import MODELS_DIR, REPORTS_DIR, SYNTH_DIR, load_config
from grid_up_anomaly_detection.ai.engine import BUFFER_HOURS, RiskEngine
from grid_up_anomaly_detection.ai.ml import MLDetector
from grid_up_anomaly_detection.ai.schema import CANONICAL_COLUMNS


######
def max_rss_mb() -> float:
    """Peak resident memory, in MB. `resource` is POSIX-only, so Windows goes through ctypes."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class _Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Counters), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        c = _Counters()
        c.cb = ctypes.sizeof(c)
        if psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb):
            return c.PeakWorkingSetSize / 1e6
        return float("nan")
    import resource  # noqa: PLC0415 - POSIX only
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # ru_maxrss is bytes on macOS and kilobytes on Linux
    return rss / 1e6 if sys.platform == "darwin" else rss / 1e3



def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modules", type=int, default=100)
    ap.add_argument("--samples", type=int, default=10, help="readings per module")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    cfg = load_config()
    baselines = load_baselines(MODELS_DIR / "baselines.json")
    ml = MLDetector.load(MODELS_DIR / "iforest.joblib")
    engine = RiskEngine(cfg, baselines, ml)

    sources = sorted((SYNTH_DIR / "normal").glob("*.csv.gz"))
    if not sources:
        raise SystemExit("no synthetic data; run scripts/generate_synthetic.py first")
    frames = [pd.read_csv(p, parse_dates=["timestamp"]) for p in sources]
    for f in frames:
        f["timestamp"] = pd.to_datetime(f["timestamp"], utc=True)

    rss_before = max_rss_mb()
    module_ids, feeds = [], {}
    for i in range(args.modules):
        src = frames[i % len(frames)]
        module_id = f"SCALE-{i:03d}"
        base_id = str(src["module_id"].iloc[0])
        engine.baselines[module_id] = baselines[base_id]
        offset = (i // len(frames)) * 37          # decorrelate modules that share a source frame
        cut = 26 * 60 + offset
        buffer = src.iloc[max(0, cut - BUFFER_HOURS * 60):cut].copy()
        buffer["module_id"] = module_id
        engine.buffers[module_id] = buffer[CANONICAL_COLUMNS].reset_index(drop=True)
        feed = src.iloc[cut:cut + args.samples].copy()
        feed["module_id"] = module_id
        feeds[module_id] = feed.to_dict("records")
        module_ids.append(module_id)
    rss_primed = max_rss_mb()

    latencies: list[float] = []
    cpu_start, wall_start = time.process_time(), time.perf_counter()
    for tick in range(args.samples):
        for module_id in module_ids:
            record = feeds[module_id][tick]
            t0 = time.perf_counter()
            engine.update(record)
            latencies.append((time.perf_counter() - t0) * 1000)
    wall = time.perf_counter() - wall_start
    cpu = time.process_time() - cpu_start

    latencies.sort()
    n = len(latencies)
    result = {
        "modules": args.modules,
        "samples_per_module": args.samples,
        "total_inferences": n,
        "wall_time_s": round(wall, 2),
        "cpu_time_s": round(cpu, 2),
        "throughput_inferences_per_s": round(n / wall, 1),
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 1),
            "p50": round(latencies[n // 2], 1),
            "p95": round(latencies[int(n * 0.95)], 1),
            "p99": round(latencies[min(int(n * 0.99), n - 1)], 1),
            "max": round(latencies[-1], 1),
        },
        "buffer_rows_per_module": len(engine.buffers[module_ids[0]]),
        "max_rss_mb": {"before_priming": round(rss_before, 1), "after_priming": round(rss_primed, 1),
                       "after_run": round(max_rss_mb(), 1)},
        "cpu_cores_needed_at_1min_cadence": round(args.modules * statistics.fmean(latencies) / 1000 / 60, 3),
        "platform": sys.platform,
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "scale_test.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    print(f"\n{args.modules} modules on a 1-minute cadence need "
          f"{result['cpu_cores_needed_at_1min_cadence'] * 100:.1f}% of one core "
          f"({result['max_rss_mb']['after_run'] - rss_before:.0f} MB of buffers).")


if __name__ == "__main__":
    main()
