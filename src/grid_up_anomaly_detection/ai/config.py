from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

AI_FOLDER = Path(__file__).resolve().parent
DEFAULT_CONFIG = AI_FOLDER / "configs" / "default.yaml"
# Organizer-supplied workbook: never committed (git-ignored /data/). Override with GRIDUP_SUPPLIED_EXCEL.
SUPPLIED_EXCEL = Path(os.environ.get("GRIDUP_SUPPLIED_EXCEL", AI_FOLDER / "data" / "Istenen Veriler.xlsx"))
SYNTH_DIR = AI_FOLDER / "data" / "synthetic"
MODELS_DIR = AI_FOLDER / "models"
REPORTS_DIR = AI_FOLDER / "reports"

def load_config(path: str | Path | None = None) -> dict[str, Any]:
    with open(path or DEFAULT_CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)
