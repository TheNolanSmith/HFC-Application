"""Refresh log / audit trail.

Every run is written to a local SQLite file (always works, even offline) and,
when configured, to a Snowflake table so the whole team sees one history.
Reads prefer Snowflake (team view) and fall back to local.
"""
from __future__ import annotations

import getpass
import platform
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from .config import APP_VERSION, DATA_DIR, SQL_DIR

LOCAL_DB = DATA_DIR / "refresh_log.db"

FIELDS = [
    "RUN_ID", "BATCH_ID", "MODEL_ID", "MODEL_NAME", "LEVEL", "L3_CODES", "FILE_PATH", "STATUS",
    "TB_ROWS", "LEGEND_ROWS", "THROUGH_PERIOD", "DATA_LOADED_AT", "STARTED_AT", "FINISHED_AT",
    "SECONDS", "USER_NAME", "MACHINE", "APP_VERSION", "MESSAGE", "DATA_HASH",
]


def new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class RunRecord:
    MODEL_ID: str
    MODEL_NAME: str
    LEVEL: str
    L3_CODES: str
    FILE_PATH: str
    STARTED_AT: datetime
    BATCH_ID: str = ""
    RUN_ID: str = field(default_factory=new_id)
    STATUS: str = "FAILED"
    TB_ROWS: int | None = None
    LEGEND_ROWS: int | None = None
    THROUGH_PERIOD: date | None = None
    DATA_LOADED_AT: datetime | None = None
    FINISHED_AT: datetime | None = None
    SECONDS: float | None = None
    USER_NAME: str = field(default_factory=getpass.getuser)
    MACHINE: str = field(default_factory=platform.node)
    APP_VERSION: str = APP_VERSION
    MESSAGE: str = ""
    DATA_HASH: str | None = None

    def finish(self, status: str, message: str = "") -> "RunRecord":
        self.STATUS = status
        self.MESSAGE = (message or "")[:4000]
        self.FINISHED_AT = datetime.now().replace(microsecond=0)
        self.SECONDS = round((self.FINISHED_AT - self.STARTED_AT).total_seconds(), 1)
        return self

    def row(self) -> list:
        d = asdict(self)
        return [d[f] for f in FIELDS]


# --------------------------------------------------------------------------- local
def _local(db: Path = LOCAL_DB) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db, detect_types=sqlite3.PARSE_DECLTYPES)
    con.execute(f"CREATE TABLE IF NOT EXISTS refresh_log ({', '.join(FIELDS)})")
    have = {r[1].upper() for r in con.execute("PRAGMA table_info(refresh_log)")}
    for f in FIELDS:
        if f not in have:  # columns added in later versions
            con.execute(f"ALTER TABLE refresh_log ADD COLUMN {f}")
    return con


def _sqlite_value(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def write_local(rec: RunRecord, db: Path = LOCAL_DB) -> None:
    with _local(db) as con:
        con.execute(
            f"INSERT INTO refresh_log VALUES ({', '.join('?' * len(FIELDS))})",
            [_sqlite_value(v) for v in rec.row()],
        )


def read_local(db: Path = LOCAL_DB) -> pd.DataFrame:
    with _local(db) as con:
        df = pd.read_sql_query("SELECT * FROM refresh_log", con)
    return _typed(df)


def _typed(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=str.upper)
    for c in FIELDS:
        if c not in df.columns:
            df[c] = None
    for c in ("STARTED_AT", "FINISHED_AT", "DATA_LOADED_AT"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    df["THROUGH_PERIOD"] = pd.to_datetime(df["THROUGH_PERIOD"], errors="coerce").dt.date
    return df[FIELDS].sort_values("STARTED_AT", ascending=False, ignore_index=True)


# --------------------------------------------------------------------------- snowflake
class RefreshLog:
    def __init__(self, settings: dict, source=None, db: Path = LOCAL_DB):
        self.db = db
        self.source = source
        self.table = "" if settings.get("demo_mode") else (settings.get("logging", {}).get("snowflake_table") or "")
        self._table_ready = False
        self.last_remote_error: str | None = None

    @property
    def remote_enabled(self) -> bool:
        return bool(self.table and self.source is not None and hasattr(self.source, "query"))

    def _ensure_table(self):
        if self._table_ready:
            return
        ddl = (SQL_DIR / "refresh_log_table.sql").read_text(encoding="utf-8")
        ddl = "\n".join(l for l in ddl.splitlines() if not l.strip().startswith("--")).format(table=self.table)
        self.source.execute(ddl)
        self.source.execute(f"ALTER TABLE {self.table} ADD COLUMN IF NOT EXISTS DATA_HASH VARCHAR")
        self._table_ready = True

    def write(self, rec: RunRecord) -> None:
        write_local(rec, self.db)
        if not self.remote_enabled:
            return
        try:
            self._ensure_table()
            self.source.execute(
                f"INSERT INTO {self.table} ({', '.join(FIELDS)}) VALUES ({', '.join(['%s'] * len(FIELDS))})",
                rec.row(),
            )
            self.last_remote_error = None
        except Exception as e:  # never let logging break a refresh
            self.last_remote_error = str(e)

    def read(self) -> tuple[pd.DataFrame, str]:
        """(log, where_from)."""
        if self.remote_enabled:
            try:
                self._ensure_table()
                return _typed(self.source.query(f"SELECT * FROM {self.table} ORDER BY STARTED_AT DESC LIMIT 5000")), "Snowflake"
            except Exception as e:
                self.last_remote_error = str(e)
        return read_local(self.db), "this PC"

    def last_success(self) -> pd.DataFrame:
        """Most recent successful run per MODEL_ID."""
        log, _ = self.read()
        ok = log[log["STATUS"] == "SUCCESS"]
        return ok.sort_values("STARTED_AT").groupby("MODEL_ID", as_index=False).tail(1).set_index("MODEL_ID")
