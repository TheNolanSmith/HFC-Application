"""Refresh one or many models: back up -> pull from Snowflake -> write -> log."""
from __future__ import annotations

import shutil
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd

from .config import SECTIONS, backups_dir, layout_for, models_root
from .discovery import create_from_template, template_for
from .excel_writer import make_writer
from .refresh_log import RefreshLog, RunRecord, new_id
from .registry import Model

Log = Callable[[str], None]


@dataclass
class Result:
    model: Model
    record: RunRecord

    @property
    def ok(self) -> bool:
        return self.record.STATUS == "SUCCESS"


def combined_hash(sub: pd.DataFrame) -> str | None:
    """One fingerprint for all of a model's L3 codes (None if the freshness query has no DATA_HASH)."""
    h = sub.sort_values("L3_CODE")["DATA_HASH"].tolist() if "DATA_HASH" in sub else []
    if not h or any(x is None for x in h):
        return None
    import hashlib
    return hashlib.md5("|".join(f"{c}:{x}" for c, x in zip(sorted(sub["L3_CODE"]), h)).encode()).hexdigest()


def backup(path: Path, dest_root: Path, model_id: str, keep: int = 5) -> Path:
    dest = dest_root / model_id
    dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = dest / f"{stamp}__{path.name}"
    shutil.copy2(path, target)
    old = sorted(dest.glob(f"*__{path.name}"), reverse=True)[max(1, int(keep)):]
    for p in old:
        try:
            p.unlink()
        except OSError:
            pass
    return target


def refresh_models(
    models: list[Model],
    settings: dict,
    source,
    refresh_log: RefreshLog,
    fresh: pd.DataFrame | None = None,
    log: Log = print,
    on_done: Callable[[Result], None] | None = None,
) -> list[Result]:
    """Refresh models in order L3s first, then L2s. One Excel instance for the whole batch."""
    if fresh is None:
        log("Checking data freshness in Snowflake")
        fresh = source.freshness()
    all_codes = fresh["L3_CODE"].tolist()
    root = models_root(settings)
    batch_id = new_id() if len(models) > 1 else ""
    ordered = sorted(models, key=lambda m: (0 if m.level == "L3" else 1, m.name))
    results: list[Result] = []

    with make_writer(settings) as writer:
        for i, m in enumerate(ordered, 1):
            log(f"── [{i}/{len(ordered)}] {m.level} · {m.name}")
            codes = m.resolve_codes(all_codes)
            path = m.resolve_file(root)
            rec = RunRecord(
                MODEL_ID=m.model_id, MODEL_NAME=m.name, LEVEL=m.level, L3_CODES=",".join(codes),
                FILE_PATH=str(path), STARTED_AT=datetime.now().replace(microsecond=0), BATCH_ID=batch_id,
            )
            created = False
            try:
                if not path.exists():
                    tmpl = template_for(settings, m.level)
                    if tmpl is None:
                        raise FileNotFoundError(f"Model file not found: {path}")
                    if not path.parent.parent.exists():
                        raise FileNotFoundError(f"Company folder not found: {path.parent.parent}")
                if not codes:
                    raise RuntimeError(f"No L3 codes resolved from '{m.l3_codes}'")
                sub = fresh[fresh["L3_CODE"].isin(codes)]
                rec.THROUGH_PERIOD = sub["LATEST_PERIOD"].max() if len(sub) else None
                rec.DATA_LOADED_AT = sub["LAST_LOADED_AT"].max() if len(sub) else None
                rec.DATA_HASH = combined_hash(sub)
                if isinstance(rec.DATA_LOADED_AT, pd.Timestamp):
                    rec.DATA_LOADED_AT = rec.DATA_LOADED_AT.to_pydatetime()

                frames = {}
                for section in SECTIONS:
                    lay = layout_for(settings, m.level, section)
                    if lay is None:
                        continue
                    log(f"Pulling {m.level} {section.upper()} for {len(codes)} code(s)")
                    df = source.export(m.level, section, codes)
                    if df is None:
                        log(f"No sql/{m.level}_{section}.sql - skipping {section}")
                        continue
                    frames[section] = (lay, df)
                if "tb" not in frames:
                    raise RuntimeError(f"No TB export for {m.level} - check sql/{m.level}_tb.sql")
                if frames["tb"][1].empty:
                    raise RuntimeError("TB export returned 0 rows - refusing to wipe the model's TB.")

                if not path.exists():
                    create_from_template(template_for(settings, m.level), path)
                    created = True
                    log(f"Created {path.name} from template")
                else:
                    b = backup(path, backups_dir(settings), m.model_id, settings.get("paths", {}).get("keep_backups", 5))
                    log(f"Backed up to {b}")
                clear = [lay.sheet for sec in ("legend",) if created and sec not in frames
                         and (lay := layout_for(settings, m.level, sec))]
                counts = writer.write(path, frames, log=log, clear_sheets=clear)
                rec.TB_ROWS = counts.get("tb")
                rec.LEGEND_ROWS = counts.get("legend")
                rec.finish("SUCCESS", ("New model from template. " if created else "") + f"Through {rec.THROUGH_PERIOD}")
                log(f"✓ Done in {rec.SECONDS}s")
            except Exception as e:
                if created and path.exists():  # don't leave a half-built new model behind
                    try:
                        path.unlink()
                    except OSError:
                        pass
                rec.finish("FAILED", f"{type(e).__name__}: {e}")
                log(f"✗ {type(e).__name__}: {e}")
                log(traceback.format_exc(limit=3))
            refresh_log.write(rec)
            res = Result(m, rec)
            results.append(res)
            if on_done:
                on_done(res)
    return results
