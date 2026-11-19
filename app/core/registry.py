"""Model registry: which workbooks exist, what level they are, which L3 codes feed them.

Stored as config/models.csv so it diffs cleanly in git and can be edited in Excel
or from the app's Models page.

l3_codes column:
  L3 model  -> its single L3 code, e.g.  ARCH
  L2 model  -> either a prefix rule      prefix:A      (every L3 code starting with A)
               or an explicit list       ARCH, JEDT, DOON
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .config import CONFIG_DIR, DATA_DIR, LEVELS

REGISTRY_FILE = CONFIG_DIR / "models.csv"
DEMO_REGISTRY_FILE = DATA_DIR / "demo_models.csv"
COLUMNS = ["model_id", "level", "name", "l3_codes", "file_path", "active", "notes"]


@dataclass(frozen=True)
class Model:
    model_id: str
    level: str
    name: str
    l3_codes: str
    file_path: str
    active: bool = True
    notes: str = ""

    @property
    def is_prefix_rule(self) -> bool:
        return self.l3_codes.strip().lower().startswith("prefix:")

    def resolve_codes(self, all_codes: list[str]) -> list[str]:
        """Concrete L3 codes for this model, given every code that exists in Snowflake."""
        raw = self.l3_codes.strip()
        if self.is_prefix_rule:
            prefixes = [p.strip().upper() for p in raw.split(":", 1)[1].split(",") if p.strip()]
            return sorted(c for c in all_codes if any(c.upper().startswith(p) for p in prefixes))
        return [c.strip().upper() for c in raw.replace(";", ",").split(",") if c.strip()]

    def resolve_file(self, root: Path) -> Path:
        p = Path(self.file_path)
        return p if p.is_absolute() else root / p


def empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNS)


def load_frame(path: Path = REGISTRY_FILE) -> pd.DataFrame:
    if not Path(path).exists():
        return empty_frame()
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = ""
    df = df[COLUMNS]
    df["active"] = df["active"].astype(str).str.strip().str.lower().isin(["", "true", "1", "yes", "y"])
    return df


def validate(df: pd.DataFrame) -> list[str]:
    errors = []
    ids = df["model_id"].astype(str).str.strip()
    if (ids == "").any():
        errors.append("Every row needs a model_id.")
    dupes = ids[ids.duplicated() & (ids != "")].unique()
    if len(dupes):
        errors.append(f"Duplicate model_id: {', '.join(dupes)}")
    bad_level = df.loc[~df["level"].isin(LEVELS), "model_id"].tolist()
    if bad_level:
        errors.append(f"level must be L3 or L2 (check: {', '.join(map(str, bad_level))})")
    for _, r in df.iterrows():
        codes = str(r["l3_codes"]).strip()
        if not codes:
            errors.append(f"{r['model_id']}: l3_codes is blank")
        elif r["level"] == "L3" and ("," in codes or codes.lower().startswith("prefix:")):
            errors.append(f"{r['model_id']}: an L3 model takes a single L3 code")
        if not str(r["file_path"]).strip():
            errors.append(f"{r['model_id']}: file_path is blank")
    return errors


def save_frame(df: pd.DataFrame, path: Path = REGISTRY_FILE) -> None:
    out = df.copy()[COLUMNS]
    out["active"] = out["active"].map(lambda v: "TRUE" if bool(v) else "FALSE")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)


def load_models(path: Path = REGISTRY_FILE, active_only: bool = True) -> list[Model]:
    df = load_frame(path)
    models = [
        Model(
            model_id=str(r.model_id).strip(),
            level=str(r.level).strip(),
            name=str(r.name).strip() or str(r.model_id).strip(),
            l3_codes=str(r.l3_codes),
            file_path=str(r.file_path).strip(),
            active=bool(r.active),
            notes=str(r.notes),
        )
        for r in df.itertuples(index=False)
        if str(r.model_id).strip()
    ]
    return [m for m in models if m.active] if active_only else models


def registry_file(settings: dict) -> Path:
    """Demo mode keeps its own registry so it never touches the real one."""
    return DEMO_REGISTRY_FILE if settings.get("demo_mode") else REGISTRY_FILE
