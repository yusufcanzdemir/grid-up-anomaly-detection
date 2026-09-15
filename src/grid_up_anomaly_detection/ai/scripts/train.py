"""Fit per-module thermal baselines (commissioning window) and the Isolation Forest."""
from __future__ import annotations

import json

import pandas as pd

from grid_up_anomaly_detection.ai.baseline import fit_module_baseline, save_baselines
from grid_up_anomaly_detection.ai.config import MODELS_DIR, SYNTH_DIR, load_config
from grid_up_anomaly_detection.ai.features import build_features
from grid_up_anomaly_detection.ai.ml import MLDetector


def _read(path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def main() -> None:
    cfg = load_config()
    meta = json.loads((SYNTH_DIR / "meta.json").read_text())
    baselines, feat_frames, report = {}, [], {}
    days = cfg["baseline"]["commissioning_days"]

    files = sorted((SYNTH_DIR / "normal").glob("*.csv.gz")) + sorted((SYNTH_DIR / "scenarios").glob("*.csv.gz"))
    for f in files:
        df = _read(f)
        mid = str(df["module_id"].iloc[0])
        m = meta[mid]
        # commissioning window = first N days, always before any fault onset
        com = df[df["timestamp"] < df["timestamp"].iloc[0] + pd.Timedelta(days=days)]
        bl = fit_module_baseline(com, cfg, m["rated_a"])
        baselines[mid] = bl
        report[mid] = {"valid": bl.valid,
                       "lug_a": {k: round(v.a, 2) for k, v in bl.lug.items() if v},
                       "lug_tau": {k: v.tau for k, v in bl.lug.items() if v},
                       "lug_r2": {k: round(v.r2, 3) for k, v in bl.lug.items() if v},
                       "lug_sigma": {k: round(v.sigma, 2) for k, v in bl.lug.items() if v},
                       "cab_a": round(bl.cab.a, 2) if bl.cab else None,
                       "cab_r2": round(bl.cab.r2, 3) if bl.cab else None}
        # ML trains only on verified-normal data: the fleet modules, whole period
        if m["kind"] == "normal":
            feat_frames.append(build_features(df, bl, cfg))
        print(f"baseline {mid:22s} valid={bl.valid} r2={report[mid]['lug_r2']}")

    save_baselines(baselines, MODELS_DIR / "baselines.json")
    F = pd.concat(feat_frames)
    ml = MLDetector(cfg["ml"]["features"], cfg["ml"]["n_estimators"], cfg["seed"]).fit(
        F, cfg["ml"]["max_train_rows"], cfg["ml"]["sev_quantile"], cfg["ml"]["sev_span_k"], cfg["seed"])
    ml.save(MODELS_DIR / "iforest.joblib")
    report["_ml"] = {"n_train_rows": int(len(F)), "features": ml.features, "lo": ml.lo, "hi": ml.hi}
    (MODELS_DIR / "train_report.json").write_text(json.dumps(report, indent=2, default=str))
    print(f"\nML trained on {len(F)} normal rows -> {MODELS_DIR}")


if __name__ == "__main__":
    main()
