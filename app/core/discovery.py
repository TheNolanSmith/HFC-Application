"""Find L3 model files on the synced SharePoint drive, and create new ones from the template.

Convention (Company Financials):
    <models_root>/<CODE>_<Company name>/.Models/<CODE>_TB (Adjusted TB).xlsx   <- new template (target)
    <models_root>/<CODE>_<Company name>/.Models/<CODE>_TBv6.0 (Adjusted TB).xlsm <- old template (ignored)
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import pandas as pd

from .config import expand_path

DEFAULT_L3_PATTERN = ".Models/{code}_TB (Adjusted TB).xlsx"


def company_folder(root: Path, code: str) -> Path | None:
    """Folder whose name starts with the code followed by _, space or - (e.g. 'IVIK_Viking_Plastics')."""
    if not root.exists():
        return None
    rx = re.compile(rf"^{re.escape(code)}[\s_\-]", re.IGNORECASE)
    hits = sorted(p for p in root.iterdir() if p.is_dir() and rx.match(p.name))
    return hits[0] if hits else None


def l3_target(root: Path, code: str, pattern: str = DEFAULT_L3_PATTERN) -> Path | None:
    folder = company_folder(root, code)
    return folder / pattern.format(code=code) if folder else None


def old_versions(target: Path) -> list[str]:
    """Old-template workbooks next to the target, e.g. IVIK_TBv6.0 (Adjusted TB).xlsm."""
    if not target.parent.exists():
        return []
    code = target.name.split("_")[0]
    return sorted(p.name for p in target.parent.glob(f"{code}*.xls*")
                  if p.name != target.name and not p.name.startswith("~$"))


def template_for(settings: dict, level: str) -> Path | None:
    raw = (settings.get("paths") or {}).get(f"{level.lower()}_template") or ""
    p = expand_path(raw) if raw else None
    return p if p and p.exists() else None


def create_from_template(template: Path, target: Path) -> Path:
    if target.exists():
        raise FileExistsError(f"{target} already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template, target)
    return target


def discover_l3(root: Path, fresh: pd.DataFrame, pattern: str = DEFAULT_L3_PATTERN,
                stale_months: int = 6) -> pd.DataFrame:
    """One row per L3 code in Snowflake with where its new-template model should live."""
    newest = fresh["LATEST_PERIOD"].max() if len(fresh) else None
    rows = []
    for r in fresh.itertuples(index=False):
        code = r.L3_CODE
        folder = company_folder(root, code)
        target = folder / pattern.format(code=code) if folder else None
        months_behind = None
        if newest is not None and r.LATEST_PERIOD is not None:
            months_behind = (newest.year - r.LATEST_PERIOD.year) * 12 + newest.month - r.LATEST_PERIOD.month
        rows.append({
            "L3": code,
            "Folder": folder.name if folder else "",
            "Model": "exists" if target and target.exists() else ("will create from template" if folder else "no company folder"),
            "Old versions": ", ".join(old_versions(target)) if target else "",
            "Data through": r.LATEST_PERIOD,
            "Active": bool(folder) and (months_behind is None or months_behind <= stale_months),
            "file_path": str(target.relative_to(root)) if target else "",
            "name": folder.name.split("_", 1)[1].replace("_", " ").strip() if folder and "_" in folder.name else code,
        })
    return pd.DataFrame(rows)
