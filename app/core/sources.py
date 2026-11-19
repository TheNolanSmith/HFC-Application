"""Where data comes from: Snowflake for real runs, a generated dataset in demo mode.

Both expose the same three calls:
  freshness()                  -> DataFrame[L3_CODE, L3_NAME, LATEST_PERIOD, LAST_LOADED_AT]
  export(level, section, codes)-> DataFrame written into the workbook (None if no SQL for it)
  execute(sql, params)         -> run a statement (used by the Snowflake refresh log)
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from .config import SQL_DIR

PLACEHOLDER = re.compile(r"<<.+?>>")


class SqlNotConfigured(RuntimeError):
    pass


def read_sql(name: str) -> str | None:
    path = SQL_DIR / f"{name}.sql"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("--"))
    if PLACEHOLDER.search(body):
        raise SqlNotConfigured(
            f"sql/{name}.sql still has a <<placeholder>>. Paste your real query into it "
            "(Settings page shows which files are ready)."
        )
    return text


def sql_status() -> dict[str, str]:
    """name -> 'ready' | 'placeholder' | 'missing' for the Settings page."""
    out = {}
    for name in ("freshness", "L3_tb", "L3_legend", "L2_tb", "L2_legend"):
        try:
            out[name] = "ready" if read_sql(name) is not None else "missing"
        except SqlNotConfigured:
            out[name] = "placeholder"
    return out


def _normalize_freshness(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=str.upper)
    for c in ("L3_CODE", "L3_NAME", "LATEST_PERIOD", "LAST_LOADED_AT"):
        if c not in df.columns:
            df[c] = None
    df["L3_CODE"] = df["L3_CODE"].astype(str).str.strip().str.upper()
    df["LATEST_PERIOD"] = pd.to_datetime(df["LATEST_PERIOD"]).dt.date
    df["LAST_LOADED_AT"] = pd.to_datetime(df["LAST_LOADED_AT"])
    return df[["L3_CODE", "L3_NAME", "LATEST_PERIOD", "LAST_LOADED_AT"]]


# --------------------------------------------------------------------------- Snowflake
class SnowflakeSource:
    name = "Snowflake"

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._conn = None

    def _connect_kwargs(self) -> dict:
        c = self.cfg
        kw = {
            "account": c.get("account"),
            "user": c.get("user"),
            "role": c.get("role") or None,
            "warehouse": c.get("warehouse") or None,
            "database": c.get("database") or None,
            "schema": c.get("schema") or None,
            "client_session_keep_alive": True,
            "application": "HFC-Application",
        }
        auth = (c.get("authenticator") or "externalbrowser").lower()
        if auth == "externalbrowser":
            # Cache the SSO token so the browser pop-up doesn't fire on every connect.
            kw.update(authenticator="externalbrowser", client_store_temporary_credential=True)
        elif auth == "snowflake_jwt":
            kw.update(
                authenticator="SNOWFLAKE_JWT",
                private_key_file=os.path.expanduser(c.get("private_key_file") or ""),
            )
            pwd = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE")
            if pwd:
                kw["private_key_file_pwd"] = pwd
        elif auth == "snowflake":
            pwd = os.environ.get("SNOWFLAKE_PASSWORD")
            if not pwd:
                raise RuntimeError("Set the SNOWFLAKE_PASSWORD environment variable, or switch authenticator.")
            kw["password"] = pwd
        else:
            raise RuntimeError(f"Unknown authenticator '{auth}'")
        missing = [k for k in ("account", "user") if not kw.get(k)]
        if missing:
            raise RuntimeError(f"Snowflake settings missing: {', '.join(missing)} (Settings page).")
        return {k: v for k, v in kw.items() if v is not None}

    @property
    def conn(self):
        if self._conn is None or self._conn.is_closed():
            import snowflake.connector

            self._conn = snowflake.connector.connect(**self._connect_kwargs())
        return self._conn

    def query(self, sql: str, params: dict | None = None) -> pd.DataFrame:
        cur = self.conn.cursor()
        try:
            cur.execute(sql, params or {})
            try:
                return cur.fetch_pandas_all()
            except Exception:  # non-arrow result (e.g. SHOW) or empty
                cols = [d[0] for d in (cur.description or [])]
                return pd.DataFrame(cur.fetchall(), columns=cols)
        finally:
            cur.close()

    def execute(self, sql: str, params=None) -> None:
        cur = self.conn.cursor()
        try:
            cur.execute(sql, params)
        finally:
            cur.close()

    def executemany(self, sql: str, rows: list) -> None:
        cur = self.conn.cursor()
        try:
            cur.executemany(sql, rows)
        finally:
            cur.close()

    def whoami(self) -> dict:
        df = self.query("SELECT CURRENT_USER() AS U, CURRENT_ROLE() AS R, CURRENT_WAREHOUSE() AS W")
        return df.iloc[0].to_dict()

    def freshness(self) -> pd.DataFrame:
        return _normalize_freshness(self.query(read_sql("freshness")))

    def export(self, level: str, section: str, codes: list[str]) -> pd.DataFrame | None:
        sql = read_sql(f"{level}_{section}")
        if sql is None:
            return None
        if not codes:
            raise RuntimeError("No L3 codes resolved for this model.")
        return self.query(sql, {"l3_codes": tuple(codes)})

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None


# --------------------------------------------------------------------------- Demo
DEMO_COMPANIES = [
    ("ARCH", "Archer Wire"),
    ("ADOO", "Doonan Trailers"),
    ("ARRT", "Road Ready Trailers"),
    ("JEDT", "JED Transportation"),
    ("PREM", "Premier Transportation"),
    ("TXBR", "Texas Bragg"),
]


class DemoSource:
    """Deterministic fake data so the whole app can be clicked through without Snowflake."""

    name = "Demo data"

    def __init__(self, seed: int = 7):
        self.seed = seed
        today = date.today()
        self.month_end = (today.replace(day=1) - timedelta(days=1))

    def whoami(self) -> dict:
        return {"U": "DEMO_USER", "R": "DEMO_ROLE", "W": "DEMO_WH"}

    def freshness(self) -> pd.DataFrame:
        rows = []
        for i, (code, name) in enumerate(DEMO_COMPANIES):
            # Every other company is a month behind; loaded-at staggered over the last week.
            period = self.month_end if i % 2 == 0 else (self.month_end.replace(day=1) - timedelta(days=1))
            loaded = datetime.now().replace(microsecond=0) - timedelta(hours=6 + 20 * i)
            rows.append((code, name, period, loaded))
        return _normalize_freshness(pd.DataFrame(rows, columns=["L3_CODE", "L3_NAME", "LATEST_PERIOD", "LAST_LOADED_AT"]))

    def export(self, level: str, section: str, codes: list[str]) -> pd.DataFrame | None:
        rng = np.random.default_rng(self.seed + len(codes))
        if section == "legend":
            names = dict(DEMO_COMPANIES)
            return pd.DataFrame(
                {"L3_CODE": codes, "L3_NAME": [names.get(c, c) for c in codes], "ENTITY_COUNT": rng.integers(1, 6, len(codes))}
            )
        periods = pd.date_range(end=self.month_end, periods=12, freq="ME").date
        accounts = [("1000", "Cash"), ("1200", "Accounts Receivable"), ("2000", "Accounts Payable"),
                    ("2600", "Acquisition Loan"), ("4000", "Revenue"), ("5000", "COGS"), ("6000", "SG&A")]
        recs = []
        for c in codes:
            for p in periods:
                for num, desc in accounts:
                    bal = float(np.round(rng.normal(0, 250_000), 2))
                    row = {"L3_CODE": c, "PERIOD_END_DATE": p}
                    if level == "L3":
                        row.update(PORTCO_ACCOUNT=num, PORTCO_ACCOUNT_DESC=desc)
                    row.update(HFC_ACCOUNT=num, PERIODIC_BALANCE=bal, PERPETUAL_BALANCE=bal * 3)
                    recs.append(row)
        return pd.DataFrame(recs)

    def execute(self, sql: str, params=None) -> None:  # pragma: no cover - demo never logs remotely
        pass

    def close(self):
        pass
