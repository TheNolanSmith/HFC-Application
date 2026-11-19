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


_SAFE_CODE = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")


def sql_in(values) -> str:
    """('A', 'B') literal for an IN clause. Rendered here rather than via driver binding:
    snowflake-connector 3.x and 5.x expand list/tuple parameters differently. Values are
    restricted to code-like strings, so nothing can be injected."""
    vals = list(values)
    bad = [v for v in vals if not _SAFE_CODE.match(str(v))]
    if bad:
        raise ValueError(f"Unexpected characters in code(s): {bad}")
    if not vals:
        raise ValueError("Empty code list")
    return "(" + ", ".join(f"'{v}'" for v in vals) + ")"


def read_sql(name: str) -> str | None:
    path = SQL_DIR / f"{name}.sql"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("--"))
    if not body.strip():
        return None  # comment-only file = section switched off
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
    for c in ("L3_CODE", "L3_NAME", "LATEST_PERIOD", "LAST_LOADED_AT", "DATA_HASH"):
        if c not in df.columns:
            df[c] = None
    df["L3_CODE"] = df["L3_CODE"].astype(str).str.strip().str.upper()
    df["LATEST_PERIOD"] = pd.to_datetime(df["LATEST_PERIOD"]).dt.date
    df["LAST_LOADED_AT"] = pd.to_datetime(df["LAST_LOADED_AT"])
    df["DATA_HASH"] = df["DATA_HASH"].map(lambda v: None if v is None or pd.isna(v) else str(v))
    return df[["L3_CODE", "L3_NAME", "LATEST_PERIOD", "LAST_LOADED_AT", "DATA_HASH"]]


# --------------------------------------------------------------------------- dbt profile
_ENV_VAR = re.compile(r"""\{\{\s*env_var\(\s*['"]([^'"]+)['"]\s*(?:,\s*['"]([^'"]*)['"]\s*)?\)\s*\}\}""")


def _render(v):
    if not isinstance(v, str):
        return v
    return _ENV_VAR.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), v)


def dbt_profile_settings(c: dict) -> dict:
    """Snowflake settings borrowed from a dbt profiles.yml, so credentials live in one place."""
    import yaml

    path = os.path.expanduser(c.get("dbt_profiles_path") or "~/.dbt/profiles.yml")
    if not os.path.exists(path):
        raise RuntimeError(f"dbt profiles.yml not found at {path}")
    with open(path, encoding="utf-8") as f:
        profiles = yaml.safe_load(f) or {}
    name = c.get("dbt_profile") or "hfc_dbt"
    prof = profiles.get(name)
    if not prof:
        raise RuntimeError(f"Profile '{name}' not in {path} (found: {', '.join(profiles)})")
    target = c.get("dbt_target") or prof.get("target")
    out = {k: _render(v) for k, v in (prof.get("outputs", {}).get(target) or {}).items()}
    if not out:
        raise RuntimeError(f"Target '{target}' not in profile '{name}'")
    if out.get("type") != "snowflake":
        raise RuntimeError(f"Profile '{name}.{target}' is type {out.get('type')}, not snowflake")
    res = {k: out.get(k) for k in ("account", "user", "role", "warehouse", "database", "schema")}
    if out.get("private_key_path"):
        res.update(authenticator="snowflake_jwt", private_key_file=out["private_key_path"],
                   _key_pwd=out.get("private_key_passphrase"))
    elif out.get("password"):
        res.update(authenticator="snowflake", _password=out["password"])
    else:
        res["authenticator"] = out.get("authenticator") or "externalbrowser"
    return res


# --------------------------------------------------------------------------- Snowflake
class SnowflakeSource:
    name = "Snowflake"

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._conn = None

    def _connect_kwargs(self) -> dict:
        c = self.cfg
        if (c.get("authenticator") or "").lower() == "dbt_profile":
            c = {**dbt_profile_settings(c), **{k: v for k, v in c.items() if v and k in ("role", "warehouse", "database", "schema")}}
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
            pwd = c.get("_key_pwd") or os.environ.get("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE")
            if pwd:
                kw["private_key_file_pwd"] = pwd
        elif auth == "snowflake":
            pwd = c.get("_password") or os.environ.get("SNOWFLAKE_PASSWORD")
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
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
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

    def catalog(self, database: str, schemas: tuple[str, ...] = ("MARTS", "CORE", "REPORTS")) -> pd.DataFrame:
        """Every table/view column in the given schemas - used to write the export SQL."""
        return self.query(
            f"""SELECT c.TABLE_SCHEMA, c.TABLE_NAME, t.TABLE_TYPE, t.ROW_COUNT, c.ORDINAL_POSITION,
                       c.COLUMN_NAME, c.DATA_TYPE, t.COMMENT AS TABLE_COMMENT
                FROM {database}.INFORMATION_SCHEMA.COLUMNS c
                JOIN {database}.INFORMATION_SCHEMA.TABLES t
                  ON t.TABLE_SCHEMA = c.TABLE_SCHEMA AND t.TABLE_NAME = c.TABLE_NAME
                WHERE c.TABLE_SCHEMA IN {sql_in(schemas)}
                ORDER BY 1, 2, 5"""
        )

    def export(self, level: str, section: str, codes: list[str]) -> pd.DataFrame | None:
        sql = read_sql(f"{level}_{section}")
        if sql is None:
            return None
        if not codes:
            raise RuntimeError("No L3 codes resolved for this model.")
        return self.query(sql.replace("%(l3_codes)s", sql_in(codes)))

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
            rows.append((code, name, period, loaded, f"h{i}"))
        return _normalize_freshness(pd.DataFrame(rows, columns=["L3_CODE", "L3_NAME", "LATEST_PERIOD", "LAST_LOADED_AT", "DATA_HASH"]))

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
