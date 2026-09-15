"""Score every scenario run and write the evaluation report + sample inference outputs."""
from __future__ import annotations

import json

import pandas as pd

from grid_up_anomaly_detection.ai.baseline import load_baselines
from grid_up_anomaly_detection.ai.config import MODELS_DIR, REPORTS_DIR, SYNTH_DIR, load_config
from grid_up_anomaly_detection.ai.engine import SCHEMA_VERSION, RiskEngine
from grid_up_anomaly_detection.ai.evaluation import evaluate_run, summarize
from grid_up_anomaly_detection.ai.ml import MLDetector
from grid_up_anomaly_detection.ai.risk import STATUSES

COLS = ["scenario", "detected", "max_status", "max_risk", "min_health", "lead_time_h", "naive_lead_time_h",
        "detection_delay_h", "naive_detection_delay_h", "diagnosis", "diagnosis_correct",
        "false_warning_per_module_day", "benign_ok"]


def pick_status_examples(scored, eng, module_id: str, examples: dict, ranks: dict) -> None:
    """Keep one representative payload per status across all runs.

    Deterministic choice: the row with the most active reasons, then the highest risk - so the
    frozen contract shows a rich, realistic payload rather than the first row that happened to match.
    """
    evidence_cols = [c for c in scored.columns if c.startswith("eff_")]
    n_reasons = (scored[evidence_cols] > 0.05).sum(axis=1)
    for status in STATUSES:
        mask = scored["status"] == status
        if not mask.any():
            continue
        # NORMAL should look like a quiet, healthy module; the alarm states should show a rich
        # explanation, since that is what the dashboard has to be able to render.
        rich = status != "NORMAL"
        candidates = pd.DataFrame({"n": n_reasons[mask], "risk": scored.loc[mask, "risk"]})
        best_ts = candidates.sort_values(["n", "risk"], ascending=not rich).index[0]
        n, risk = int(candidates.loc[best_ts, "n"]), int(candidates.loc[best_ts, "risk"])
        rank = (n, risk) if rich else (-n, -risk)
        if rank > ranks.get(status, (-10 ** 6, -10 ** 6)):
            ranks[status] = rank
            examples[status] = eng.output(scored, module_id, scored.index.get_loc(best_ts))


def main() -> None:
    cfg = load_config()
    meta = json.loads((SYNTH_DIR / "meta.json").read_text())
    eng = RiskEngine(cfg, load_baselines(MODELS_DIR / "baselines.json"), MLDetector.load(MODELS_DIR / "iforest.joblib"))
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    for stale in REPORTS_DIR.glob("timeline_*.csv"):   # scenario renames would leave orphans behind
        stale.unlink()
    rows, samples = [], {}
    examples: dict[str, dict] = {}      # one representative payload per status
    example_rank: dict[str, tuple] = {}

    for f in sorted(SYNTH_DIR.glob("*/*.csv.gz")):
        df = pd.read_csv(f, parse_dates=["timestamp"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        mid = str(df["module_id"].iloc[0])
        m = meta[mid]
        scored = eng.score(df)
        rows.append(evaluate_run(scored, m, df))
        # two representative outputs per run: the moment we first alarm, and the worst moment
        warn = scored.index[scored["status_code"] >= 2]
        peak = int(scored["risk"].to_numpy().argmax())
        first = scored.index.get_loc(warn[0]) if len(warn) else peak
        samples[m["scenario"]] = {"first_alarm": eng.output(scored, mid, first),
                                  "peak": eng.output(scored, mid, peak)}
        pick_status_examples(scored, eng, mid, examples, example_rank)
        scored[["risk", "health", "status", "condition"]].resample("1h").agg(
            {"risk": "max", "health": "min", "status": "last", "condition": "last"}).to_csv(
            REPORTS_DIR / f"timeline_{m['scenario']}.csv")

    tbl = summarize(rows)
    tbl.to_csv(REPORTS_DIR / "evaluation.csv", index=False)
    contract = {
        "schema_version": SCHEMA_VERSION,
        "description": "Frozen inference payload. See ai/docs/inference_contract.md.",
        "generated_by": "ai/scripts/evaluate.py (deterministic: fixed seed, no wall-clock inputs)",
        "examples": {status: examples[status] for status in STATUSES if status in examples},
        "by_scenario": samples,
    }
    (REPORTS_DIR / "sample_outputs.json").write_text(json.dumps(contract, indent=2, default=str, ensure_ascii=False))

    faults = tbl[tbl["expected_condition"] != "NONE"]
    benign = tbl[tbl["expected_condition"] == "NONE"]
    md = ["# Evaluation (synthetic scenarios)\n", tbl[COLS].to_markdown(index=False), "\n## Headline\n",
          f"- fault scenarios detected: {int(faults['detected'].sum())}/{len(faults)}",
          f"- diagnosis correct: {int(faults['diagnosis_correct'].sum())}/{len(faults)}",
          f"- median early-warning lead time: {faults['lead_time_h'].median():.1f} h "
          f"(threshold comparator: {faults['naive_lead_time_h'].median() if faults['naive_lead_time_h'].notna().any() else 0:.1f} h)",
          f"- benign runs within expected status: {int(benign['benign_ok'].astype(bool).sum())}/{len(benign)}",
          f"- false WARNING episodes per module-day (pre-onset): {tbl['false_warning_per_module_day'].mean():.3f}"]
    (REPORTS_DIR / "evaluation.md").write_text("\n".join(md))
    print("\n".join(md))


if __name__ == "__main__":
    main()
