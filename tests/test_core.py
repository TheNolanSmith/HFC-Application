from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from openpyxl import load_workbook

from core import config, demo, registry, refresh_log, status
from core.config import SheetLayout
from core.excel_writer import OpenpyxlWriter, WorkbookLocked, assert_not_open, col_range, to_rows
from core.refresh import refresh_models
from core.registry import Model
from core.sources import DemoSource, SqlNotConfigured, read_sql


CODES = ["ARCH", "ADOO", "ARRT", "JEDT"]


def test_prefix_rule_and_list():
    assert Model("x", "L2", "g", "prefix:A", "f").resolve_codes(CODES) == ["ADOO", "ARCH", "ARRT"]
    assert Model("x", "L2", "g", "prefix: A, J", "f").resolve_codes(CODES) == ["ADOO", "ARCH", "ARRT", "JEDT"]
    assert Model("x", "L2", "g", "jedt; arch", "f").resolve_codes(CODES) == ["JEDT", "ARCH"]
    assert Model("x", "L3", "c", "ARCH", "f").resolve_codes(CODES) == ["ARCH"]


def test_registry_validation():
    df = pd.DataFrame([
        ["a", "L3", "A", "ARCH,JEDT", "a.xlsx", True, ""],
        ["a", "L9", "B", "", "", True, ""],
    ], columns=registry.COLUMNS)
    errs = " | ".join(registry.validate(df))
    assert "single L3 code" in errs and "Duplicate" in errs and "L3 or L2" in errs and "blank" in errs


def test_registry_roundtrip(tmp_path):
    df = pd.DataFrame([["a", "L3", "A", "ARCH", "a.xlsx", False, ""]], columns=registry.COLUMNS)
    registry.save_frame(df, tmp_path / "m.csv")
    assert registry.load_models(tmp_path / "m.csv") == []
    assert len(registry.load_models(tmp_path / "m.csv", active_only=False)) == 1


def test_col_range_and_rows():
    assert col_range("A:R") == (1, 18)
    assert col_range("") is None
    rows = to_rows(pd.DataFrame({"d": [date(2026, 1, 31)], "n": [float("nan")], "s": ["x"]}))
    assert rows == [[datetime(2026, 1, 31), None, "x"]]


def test_placeholder_sql_is_rejected(tmp_path, monkeypatch):
    import core.sources as src
    monkeypatch.setattr(src, "SQL_DIR", tmp_path)
    (tmp_path / "freshness.sql").write_text("SELECT * FROM <<YOUR_TABLE>>")
    with pytest.raises(SqlNotConfigured):
        src.read_sql("freshness")


def test_lock_detection(tmp_path):
    p = tmp_path / "Model.xlsx"
    p.write_bytes(b"x")
    assert_not_open(p)
    (tmp_path / "~$Model.xlsx").write_bytes(b"x")
    with pytest.raises(WorkbookLocked):
        assert_not_open(p)


def _status_row(through, loaded, fresh_period, fresh_loaded, tmp_path):
    f = tmp_path / "m.xlsx"
    f.write_bytes(b"x")
    m = Model("m", "L3", "M", "ARCH", str(f))
    fresh = pd.DataFrame({"L3_CODE": ["ARCH"], "L3_NAME": ["A"], "LATEST_PERIOD": [fresh_period],
                          "LAST_LOADED_AT": [pd.Timestamp(fresh_loaded)]})
    last = pd.DataFrame(
        [{"MODEL_ID": "m", "THROUGH_PERIOD": through, "DATA_LOADED_AT": pd.Timestamp(loaded),
          "FINISHED_AT": pd.Timestamp(loaded), "USER_NAME": "n"}]
    ).set_index("MODEL_ID") if through else pd.DataFrame().rename_axis("MODEL_ID")
    return status.model_status(m, fresh, last, tmp_path)["Status"]


def test_status_logic(tmp_path):
    oct31, sep30 = date(2026, 10, 31), date(2026, 9, 30)
    t0 = datetime(2026, 11, 1, 8)
    assert _status_row(None, None, oct31, t0, tmp_path) == "Never refreshed"
    assert _status_row(sep30, t0, oct31, t0, tmp_path) == "New period"
    assert _status_row(oct31, t0, oct31, t0 + timedelta(hours=1), tmp_path) == "Updated data"
    assert _status_row(oct31, t0, oct31, t0, tmp_path) == "Current"


def test_end_to_end_demo(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "DEMO_DIR", tmp_path / "models")
    monkeypatch.setattr(demo, "DEMO_REGISTRY_FILE", tmp_path / "models.csv")
    demo.ensure_demo(reset=True)
    settings = config.load_settings(tmp_path / "none.yaml")
    settings["demo_mode"] = True
    settings["paths"]["backups_dir"] = str(tmp_path / "bk")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)  # models_root -> tmp/demo_models
    import core.refresh as rf
    monkeypatch.setattr(rf, "models_root", lambda s: tmp_path / "models")

    models = registry.load_models(tmp_path / "models.csv")
    log = refresh_log.RefreshLog(settings, db=tmp_path / "log.db")
    src = DemoSource()
    results = refresh_models(models, settings, src, log, log=lambda m: None)
    by_id = {r.model.model_id: r for r in results}

    assert not by_id["L3_GONE"].ok and "not found" in by_id["L3_GONE"].record.MESSAGE
    arch = by_id["L3_ARCH"]
    assert arch.ok and arch.record.TB_ROWS == 12 * 7
    l2a = by_id["L2_A"]
    assert l2a.ok and l2a.record.L3_CODES == "ADOO,ARCH,ARRT"

    wb = load_workbook(tmp_path / "models" / "L3/ARCH_TB (Adjusted TB).xlsx")
    tb = wb["TB"]
    assert tb["A2"].value == "ARCH" and tb["A85"].value == "ARCH" and tb["A86"].value is None
    assert wb["Legend"]["B2"].value == "Archer Wire"
    assert list((tmp_path / "bk" / "L3_ARCH").glob("*.xlsx"))

    # second run with fewer rows clears leftovers
    small = DemoSource()
    small.export = lambda level, section, codes: pd.DataFrame({"L3_CODE": ["ARCH"], "PERIOD_END_DATE": [date(2026, 10, 31)]}) if section == "tb" else None
    refresh_models([m for m in models if m.model_id == "L3_ARCH"], settings, small, log, log=lambda m: None)
    tb = load_workbook(tmp_path / "models" / "L3/ARCH_TB (Adjusted TB).xlsx")["TB"]
    assert tb["A3"].value is None and tb["C2"].value is None and tb["A2"].value == "ARCH"

    hist = log.read()[0]
    assert len(hist) == len(models) + 1
    board = status.board(models, src.freshness(), log.last_success(), tmp_path / "models")
    assert board.iloc[0]["Status"] == "Missing file"
    assert set(board["Status"]) <= set(status.STATUS_ORDER)


def test_refuses_empty_tb(tmp_path, monkeypatch):
    f = tmp_path / "m.xlsx"
    demo._make_workbook(f, "L3")
    settings = config.load_settings(tmp_path / "none.yaml")
    settings["demo_mode"] = True
    settings["paths"]["backups_dir"] = str(tmp_path / "bk")
    src = DemoSource()
    src.export = lambda *a: pd.DataFrame(columns=["L3_CODE"])
    res = refresh_models([Model("m", "L3", "M", "ARCH", str(f))], settings, src,
                         refresh_log.RefreshLog(settings, db=tmp_path / "l.db"), log=lambda m: None)
    assert not res[0].ok and "0 rows" in res[0].record.MESSAGE


def test_dbt_profile(tmp_path, monkeypatch):
    from core.sources import SnowflakeSource, dbt_profile_settings

    p = tmp_path / "profiles.yml"
    p.write_text("""hfc_dbt:
  outputs:
    dev:
      type: snowflake
      account: acct-1
      user: SVC
      private_key_path: "C:/k/rsa_key.p8"
      private_key_passphrase: "{{ env_var('PP', 'fallback') }}"
      role: R
      database: DB
      warehouse: WH
      schema: CORE
  target: dev
""")
    s = dbt_profile_settings({"dbt_profiles_path": str(p)})
    assert s["account"] == "acct-1" and s["authenticator"] == "snowflake_jwt" and s["_key_pwd"] == "fallback"
    kw = SnowflakeSource({"authenticator": "dbt_profile", "dbt_profiles_path": str(p),
                          "schema": "MARTS", "warehouse": ""})._connect_kwargs()
    assert kw["schema"] == "MARTS" and kw["warehouse"] == "WH" and kw["private_key_file_pwd"] == "fallback"
    assert kw["authenticator"] == "SNOWFLAKE_JWT" and "_key_pwd" not in kw


def test_hash_based_status(tmp_path):
    f = tmp_path / "m.xlsx"
    f.write_bytes(b"x")
    m = Model("m", "L3", "M", "ARCH", str(f))
    from core.refresh import combined_hash

    def fresh(h):
        return pd.DataFrame({"L3_CODE": ["ARCH"], "L3_NAME": [None], "LATEST_PERIOD": [date(2026, 10, 31)],
                             "LAST_LOADED_AT": [pd.NaT], "DATA_HASH": [h]})
    last = pd.DataFrame([{"MODEL_ID": "m", "THROUGH_PERIOD": date(2026, 10, 31), "DATA_LOADED_AT": pd.NaT,
                          "FINISHED_AT": pd.Timestamp("2026-11-01"), "USER_NAME": "n",
                          "DATA_HASH": combined_hash(fresh("111"))}]).set_index("MODEL_ID")
    assert status.model_status(m, fresh("111"), last, tmp_path)["Status"] == "Current"
    assert status.model_status(m, fresh("222"), last, tmp_path)["Status"] == "Updated data"


def test_comment_only_sql_is_off(tmp_path, monkeypatch):
    import core.sources as src
    monkeypatch.setattr(src, "SQL_DIR", tmp_path)
    (tmp_path / "L3_legend.sql").write_text("-- off\n-- nothing here\n")
    assert src.read_sql("L3_legend") is None


def test_sql_in_and_export_rendering():
    from core.sources import SnowflakeSource, sql_in
    assert sql_in(["IVIK"]) == "('IVIK')"
    assert sql_in(["MFMF", "MFHE"]) == "('MFMF', 'MFHE')"
    with pytest.raises(ValueError):
        sql_in(["A'; DROP TABLE x;--"])
    seen = {}
    src = SnowflakeSource({})
    src.query = lambda sql, params=None: seen.setdefault("sql", sql) and pd.DataFrame()
    src.export("L2", "tb", ["MFMF", "MFHE"])
    assert "WHERE L3 IN ('MFMF', 'MFHE')" in seen["sql"] and "%(" not in seen["sql"]


def test_discovery_and_create_from_template(tmp_path, monkeypatch):
    from core import discovery
    root = tmp_path / "Company Financials"
    (root / "IVIK_Viking_Plastics" / ".Models").mkdir(parents=True)
    (root / "IVIK_Viking_Plastics" / ".Models" / "IVIK_TBv6.0 (Adjusted TB).xlsm").write_bytes(b"x")
    (root / "TJED_JED_Transportation").mkdir()
    fresh = pd.DataFrame({"L3_CODE": ["IVIK", "TJED", "ZZZZ"], "L3_NAME": None,
                          "LATEST_PERIOD": [date(2026, 10, 31), date(2025, 1, 31), date(2026, 10, 31)],
                          "LAST_LOADED_AT": pd.NaT, "DATA_HASH": ["a", "b", "c"]})
    scan = discovery.discover_l3(root, fresh).set_index("L3")
    assert scan.loc["IVIK", "Model"] == "will create from template"
    assert "IVIK_TBv6.0" in scan.loc["IVIK", "Old versions"]
    assert scan.loc["IVIK", "Active"] and not scan.loc["TJED", "Active"] and scan.loc["ZZZZ", "Folder"] == ""
    assert scan.loc["IVIK", "name"] == "Viking Plastics"

    tmpl = tmp_path / "XXXX_TB (Adjusted TB) NEWNEW.xlsx"
    demo._make_workbook(tmpl, "L3")
    from openpyxl import load_workbook as lw
    wb = lw(tmpl); wb["Legend"]["A2"] = "Sample Co"; wb["Legend"]["H2"] = "=MINIFS(TB!A:A,TB!C:C,F2)"; wb.save(tmpl)
    settings = config.load_settings(tmp_path / "none.yaml")
    settings.update(demo_mode=True)
    settings["paths"].update(l3_template=str(tmpl), backups_dir=str(tmp_path / "bk"))
    monkeypatch.setattr("core.refresh.models_root", lambda s: root)
    m = Model("L3_IVIK", "L3", "Viking", "IVIK", scan.loc["IVIK", "file_path"])
    st_row = status.model_status(m, fresh, pd.DataFrame().rename_axis("MODEL_ID"), root, can_create=True)
    assert st_row["Status"] == "New model"
    src = DemoSource()
    real_export = src.export
    src.export = lambda level, section, codes: None if section == "legend" else real_export(level, section, codes)
    res = refresh_models([m], settings, src, refresh_log.RefreshLog(settings, db=tmp_path / "l.db"),
                         fresh=fresh, log=lambda x: None)
    assert res[0].ok and "New model" in res[0].record.MESSAGE
    out = lw(root / "IVIK_Viking_Plastics/.Models/IVIK_TB (Adjusted TB).xlsx")
    assert out["Legend"]["A2"].value is None and out["Legend"]["H2"].value.startswith("=")
