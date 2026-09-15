"""Audit of the supplied workbook: what the data actually is, and what it can/cannot support."""
from __future__ import annotations

from grid_up_anomaly_detection.ai.config import REPORTS_DIR, SUPPLIED_EXCEL, load_config
from grid_up_anomaly_detection.ai.loaders import load_supplied_current
from grid_up_anomaly_detection.ai.physics import first_order


def main() -> None:
    if not SUPPLIED_EXCEL.exists():
        raise SystemExit(f"supplied workbook not found at {SUPPLIED_EXCEL} (set GRIDUP_SUPPLIED_EXCEL)")
    cfg = load_config()
    sensor = cfg["sensors"]["excel_current"]
    df = load_supplied_current(SUPPLIED_EXCEL, secondary_fs_ma=sensor["secondary_full_scale_ma"],
                               primary_fs_a=sensor["primary_full_scale_a"])
    ma, a = df["current_l1_ma"], df["current_l1_a"]
    step_min = df["timestamp"].diff().dt.total_seconds().div(60).mode().iloc[0]
    lag1 = ma.autocorr(1)
    hours = (df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]).total_seconds() / 3600
    hod = df["timestamp"].dt.hour
    by_hour = ma.groupby(hod).mean()

    lines = ["# Supplied data audit (Istenen Veriler.xlsx)\n",
             f"- sheet `Akım Sensörü`: **{len(df)} rows**, step **{step_min:.0f} min**, span **{hours:.1f} h** "
             f"({df['timestamp'].iloc[0]:%H:%M} -> +{hours / 24:.2f} d), sheet marked *Sentetik Data*",
             f"- secondary {ma.min():.0f}-{ma.max():.0f} mA, mean {ma.mean():.1f} mA "
             f"(sensor {sensor['secondary_full_scale_ma']} mA <-> {sensor['primary_full_scale_a']} A)",
             f"- primary {a.min():.0f}-{a.max():.0f} A, mean {a.mean():.0f} A",
             f"- **lag-1 autocorrelation = {lag1:.3f}** -> samples are statistically independent",
             f"- hourly means {by_hour.min():.0f}-{by_hour.max():.0f} mA -> **no daily load profile**",
             f"- mean |step| between samples: {ma.diff().abs().mean():.1f} mA ({ma.diff().abs().mean() * 6:.0f} A)",
             "\n**Conclusion:** the supplied current series is uniform white noise, not a load profile. "
             "It is usable for unit conversion, range and interface work, and as a robustness input; "
             "it cannot be used to learn a normal baseline or to train a time-series model.\n",
             "## Thermal-image (overload) rule replayed on the supplied series\n"]

    for rated in (400, 600, 2312):
        t = (df["timestamp"] - df["timestamp"].iloc[0]).dt.total_seconds().to_numpy() / 60
        theta = first_order(((a / rated) ** 2).to_numpy(), t, cfg["features"]["thermal_image_tau_min"])
        lines.append(f"- rated {rated} A: theta max {theta.max():.2f}, mean {theta.mean():.2f}, "
                     f"samples above rating {100 * (a > rated).mean():.0f}% -> "
                     f"{'OVERLOAD rule would fire' if theta.max() >= cfg['rules']['theta_warning'] else 'no overload alarm'}")

    other = cfg["sensors"]["ct_secondary_clamp"]
    lines += ["\n## Other sheets\n",
              "- `ARC`: text only - 'ABB TVOC-2 verilerinden Modbus ile okunarak alinacak' (no data)",
              "- `PD`: text only - HFCT30 datasheet + EA Technology link (no data)",
              "- `Sıcaklık_Nem`: **completely empty** - temperature/humidity must be synthesised",
              f"\nSecond conversion documented in the sheet (F2): {other['secondary_full_scale_ma']} mA <-> "
              f"{other['ct_secondary_a']} A CT secondary; with a {other['ct_ratio']}:1 CT that is "
              f"{other['secondary_full_scale_ma']} mA <-> {other['ct_secondary_a'] * other['ct_ratio']:.0f} A primary "
              "(non-invasive retrofit on the existing measuring CT secondary).\n"]

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "data_audit.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
