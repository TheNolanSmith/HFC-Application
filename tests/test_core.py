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


def test_placeholder_sql_is_rejected():
    with pytest.raises(SqlNotConfigured):
        read_sql("freshness")


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
    assert tb["S2"].value == "ARCH" and tb["A85"].value.startswith('=IF(T85=""')
    assert tb["A86"].value is None  # formulas stop at last data row
    assert wb["Legend"]["B2"].value == "Archer Wire"
    assert list((tmp_path / "bk" / "L3_ARCH").glob("*.xlsx"))

    # second run with fewer rows clears leftovers
    small = DemoSource()
    small.export = lambda level, section, codes: pd.DataFrame({"L3_CODE": ["ARCH"], "PERIOD_END_DATE": [date(2026, 10, 31)]}) if section == "tb" else None
    refresh_models([m for m in models if m.model_id == "L3_ARCH"], settings, small, log, log=lambda m: None)
    tb = load_workbook(tmp_path / "models" / "L3/ARCH_TB (Adjusted TB).xlsx")["TB"]
    assert tb["S3"].value is None and tb["A3"].value is None and tb["A2"].value.startswith("=")

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
