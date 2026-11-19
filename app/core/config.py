"""Settings loading. One YAML file, merged over the shipped example defaults."""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

APP_VERSION = "0.1.0"

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
SQL_DIR = REPO_ROOT / "sql"
DATA_DIR = REPO_ROOT / "data"          # local log db, demo workbooks (git-ignored)
EXAMPLE_SETTINGS = CONFIG_DIR / "settings.example.yaml"
SETTINGS_FILE = Path(os.environ.get("HFC_APP_SETTINGS", CONFIG_DIR / "settings.yaml"))

LEVELS = ("L3", "L2")
SECTIONS = ("tb", "legend")


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass(frozen=True)
class SheetLayout:
    sheet: str
    header_row: int = 1
    data_start_col: str = "A"
    formula_cols: str = ""
    table_name: str = ""

    @property
    def first_data_row(self) -> int:
        return int(self.header_row) + 1


def load_settings(path: Path | None = None) -> dict:
    with open(EXAMPLE_SETTINGS, encoding="utf-8") as f:
        base = yaml.safe_load(f) or {}
    path = Path(path) if path else SETTINGS_FILE
    if path.exists():
        with open(path, encoding="utf-8") as f:
            base = _deep_merge(base, yaml.safe_load(f) or {})
    return base


def save_settings(settings: dict, path: Path | None = None) -> None:
    path = Path(path) if path else SETTINGS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(settings, f, sort_keys=False)


def layout_for(settings: dict, level: str, section: str) -> SheetLayout | None:
    cfg = (settings.get("layouts") or {}).get(level, {}).get(section)
    if not cfg or not cfg.get("sheet"):
        return None
    return SheetLayout(
        sheet=str(cfg["sheet"]),
        header_row=int(cfg.get("header_row", 1)),
        data_start_col=str(cfg.get("data_start_col", "A")).upper(),
        formula_cols=str(cfg.get("formula_cols") or "").upper(),
        table_name=str(cfg.get("table_name") or ""),
    )


def expand_path(p: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(p or "")))


def models_root(settings: dict) -> Path:
    if settings.get("demo_mode"):
        return DATA_DIR / "demo_models"
    return expand_path(settings.get("paths", {}).get("models_root", ""))


def backups_dir(settings: dict) -> Path:
    return expand_path(settings.get("paths", {}).get("backups_dir") or str(DATA_DIR / "backups"))
