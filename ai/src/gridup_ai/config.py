from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

AI_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = AI_ROOT.parent
DEFAULT_CONFIG = AI_ROOT / "configs" / "default.yaml"
# Organizer-supplied workbook: never committed (git-ignored /data/). Override with GRIDUP_SUPPLIED_EXCEL.
SUPPLIED_EXCEL = Path(os.environ.get("GRIDUP_SUPPLIED_EXCEL", REPO_ROOT / "data" / "İstenen Veriler.xlsx"))
SYNTH_DIR = AI_ROOT / "data" / "synthetic"
MODELS_DIR = AI_ROOT / "models"
REPORTS_DIR = AI_ROOT / "reports"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    with open(path or DEFAULT_CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)
