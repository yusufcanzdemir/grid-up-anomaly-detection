"""Generate the reproducible synthetic dataset (fleet normal + scenario runs)."""
from __future__ import annotations

import argparse
import json
import shutil

from gridup_ai.config import SYNTH_DIR, load_config
from gridup_ai.simulator import ModuleParams, Scenario, fleet_params, scenario_library, simulate


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modules", type=int, default=6, help="normal fleet modules (training)")
    ap.add_argument("--normal-days", type=float, default=21)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()
    cfg = load_config()
    seed = args.seed if args.seed is not None else cfg["seed"]
    for sub in ("normal", "scenarios"):
        shutil.rmtree(SYNTH_DIR / sub, ignore_errors=True)  # stale runs would break train/evaluate
        (SYNTH_DIR / sub).mkdir(parents=True, exist_ok=True)
    meta = {}

    for i, mp in enumerate(fleet_params(args.modules, seed)):
        mid = f"PANEL-{i + 1:02d}-M1"
        scn = Scenario(f"normal_{i}", "normal", days=args.normal_days, onset_day=None,
                       profile="MV_CELL" if i % 3 == 0 else "LV_PANEL")
        df = simulate(scn, mp, seed=seed + i, module_id=mid, panel_id=f"PANEL-{i + 1:02d}")
        df.to_csv(SYNTH_DIR / "normal" / f"{mid}.csv.gz", index=False)
        meta[mid] = {"scenario": scn.name, "kind": "normal", "rated_a": mp.rated_a, "profile": scn.profile,
                     "onset": None, "failure": None, "expected_condition": "NONE", "expected_max_status": "WATCH"}
        print(f"normal  {mid:16s} {len(df):6d} rows  profile={scn.profile}")

    for j, scn in enumerate(scenario_library()):
        mp = ModuleParams()
        mid = f"DEMO-{scn.name}"
        df = simulate(scn, mp, seed=seed + 100 + j, module_id=mid, panel_id=f"DEMO-{j:02d}")
        df.to_csv(SYNTH_DIR / "scenarios" / f"{scn.name}.csv.gz", index=False)
        meta[mid] = {"scenario": scn.name, "kind": scn.kind, "rated_a": mp.rated_a, "profile": scn.profile,
                     "onset": str(df.attrs["onset"]) if df.attrs["onset"] is not None else None,
                     "failure": str(df.attrs["failure"]) if df.attrs["failure"] is not None else None,
                     "expected_condition": scn.expected_condition,
                     "expected_max_status": scn.expected_max_status,
                     "detect_level": scn.detect_level,
                     "expected_reasons": list(scn.expected_reasons)}
        print(f"scenario {scn.name:22s} {len(df):6d} rows  onset={meta[mid]['onset']} failure={meta[mid]['failure']}")

    (SYNTH_DIR / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"\nwrote {SYNTH_DIR}  (seed={seed})")


if __name__ == "__main__":
    main()
