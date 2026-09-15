"""ML anomaly layer: Isolation Forest on physics-normalised features.

Deliberately a *supporting* signal: its group weight caps ML-only risk at WATCH.
If the model is missing or fails, the engine runs rules + statistical layers only.
"""
from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest


class MLDetector:
    def __init__(self, features: list[str], n_estimators: int = 200, seed: int = 42):
        self.features = features
        self.model = IsolationForest(n_estimators=n_estimators, random_state=seed, n_jobs=-1)
        self.medians: pd.Series | None = None
        self.lo = self.hi = None

    def _matrix(self, F: pd.DataFrame) -> np.ndarray:
        X = F.reindex(columns=self.features).astype(float)
        return X.fillna(self.medians).fillna(0.0).to_numpy()

    def fit(self, F: pd.DataFrame, max_rows: int, quantile: float, span_k: float, seed: int = 42) -> "MLDetector":
        X = F.reindex(columns=self.features).astype(float)
        X = X.dropna(thresh=len(self.features) // 2)
        if len(X) > max_rows:
            X = X.sample(max_rows, random_state=seed)
        self.medians = X.median()
        Xm = X.fillna(self.medians).fillna(0.0).to_numpy()
        self.model.fit(Xm)
        s = -self.model.score_samples(Xm)
        self.lo = float(np.quantile(s, quantile))
        self.hi = self.lo + span_k * (self.lo - float(np.median(s)))
        return self

    def raw_score(self, F: pd.DataFrame) -> np.ndarray:
        return -self.model.score_samples(self._matrix(F))

    def severity(self, F: pd.DataFrame) -> np.ndarray:
        return np.clip((self.raw_score(F) - self.lo) / (self.hi - self.lo), 0.0, 1.0)

    def attributions(self, row: pd.DataFrame) -> dict[str, float]:
        """Occlusion: how much the anomaly score drops when one feature is reset to its normal median."""
        x = self._matrix(row)
        base = -self.model.score_samples(x)[0]
        drops = {}
        for j, name in enumerate(self.features):
            xr = x.copy()
            xr[0, j] = self.medians.get(name, 0.0) if self.medians is not None else 0.0
            drops[name] = max(0.0, base + self.model.score_samples(xr)[0])
        tot = sum(drops.values()) or 1.0
        return {k: round(v / tot, 3) for k, v in sorted(drops.items(), key=lambda kv: -kv[1]) if v > 0}

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @staticmethod
    def load(path: Path) -> "MLDetector | None":
        try:
            return joblib.load(path)
        except Exception:
            return None
