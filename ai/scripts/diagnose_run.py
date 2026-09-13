"""Forensics for one run: what exactly drove the risk, and when.

    python ai/scripts/diagnose_run.py normal_3 [--top 5]
"""
from __future__ import annotations

import argparse
import json

import pandas as pd

from gridup_ai.baseline import load_baselines
from gridup_ai.config import MODELS_DIR, SYNTH_DIR, load_config
from gridup_ai.engine import RiskEngine
from gridup_ai.evaluation import episodes
from gridup_ai.ml import MLDetector


def find_file(name: str, meta: dict):
    """Accept either a module id (PANEL-04-M1) or a scenario name (normal_3, loose_connection_L2)."""
    ids = {mid for mid, m in meta.items() if name in (mid, m["scenario"])}
    for p in SYNTH_DIR.glob("*/*.csv.gz"):
        if name in p.stem or p.stem in ids or any(i in p.stem for i in ids):
            return p
    raise SystemExit(f"run '{name}' not found. scenarios: {sorted(m['scenario'] for m in meta.values())}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--level", type=int, default=2)
    args = ap.parse_args()
    cfg = load_config()
    meta = json.loads((SYNTH_DIR / "meta.json").read_text())
    df = pd.read_csv(find_file(args.run, meta), parse_dates=["timestamp"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    mid = str(df["module_id"].iloc[0])
    eng = RiskEngine(cfg, load_baselines(MODELS_DIR / "baselines.json"), MLDetector.load(MODELS_DIR / "iforest.joblib"))
    scored = eng.score(df)
    m = meta[mid]

    print(f"== {mid}  scenario={m['scenario']} onset={m['onset']} failure={m['failure']}")
    print(f"   max risk {scored['risk'].max()}  max status {scored['status'].iloc[scored['status_code'].argmax()]}")
    eps = episodes(scored["status_code"], args.level)
    print(f"   episodes >= level {args.level}: {len(eps)}")
    for s, e in eps[:10]:
        print(f"     {s} -> {e}  ({(e - s).total_seconds() / 3600:.1f} h)")

    i = int(scored["risk"].to_numpy().argmax())
    row = scored.iloc[i]
    print(f"\n-- worst row {row.name}  risk={row['risk']} status={row['status']} "
          f"condition={row['condition']} ({row['condition_confidence']})")
    ev = {c[4:]: float(row[c]) for c in scored.columns if c.startswith("eff_") and row[c] > 0.01}
    fl = {c[6:]: float(row[c]) for c in scored.columns if c.startswith("floor_") and row[c] > 0}
    gr = {c[4:]: round(float(row[c]), 3) for c in scored.columns if c.startswith("grp_")}
    print("   evidence:", {k: round(v, 3) for k, v in sorted(ev.items(), key=lambda kv: -kv[1])})
    print("   floors  :", fl)
    print("   groups  :", gr, " fused:", round(float(row["risk_fused"]), 3))
    keys = ["heat_index_max", "heat_asym", "lug_resid_z_max", "cab_index", "cab_resid_z", "theta",
            "current_max_pu", "temp_max_f", "temp_internal_c", "rh", "dew_margin_c", "pd_z", "ml_sev",
            "heat_index_slope", "completeness"]
    print("   values  :", {k: (None if pd.isna(row.get(k)) else round(float(row[k]), 2)) for k in keys if k in row})
    faults = [c[6:] for c in scored.columns if c.startswith("fault_") and bool(row[c])]
    print("   faults  :", faults)

    print(f"\n-- top {args.top} evidence by time spent above 0.5 severity")
    eff = scored[[c for c in scored.columns if c.startswith("eff_")]]
    share = (eff > 0.5).mean().sort_values(ascending=False).head(args.top)
    print(share.round(4).to_string())

    print("\n-- daily maxima")
    agg = scored.resample("1D").agg({"risk": "max", "heat_index_max": "max", "heat_asym": "max",
                                     "cab_index": "max", "theta": "max", "temp_max_f": "max",
                                     "lug_resid_z_max": "max", "ml_sev": "max", "rh": "max"}).round(2)
    print(agg.to_string())


if __name__ == "__main__":
    main()
