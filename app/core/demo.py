"""Builds sample model workbooks + a registry for demo mode (data/demo_models)."""
from __future__ import annotations

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from .config import DATA_DIR
from .registry import DEMO_REGISTRY_FILE, save_frame
from .sources import DEMO_COMPANIES

DEMO_DIR = DATA_DIR / "demo_models"
HEADER_FILL = PatternFill("solid", fgColor="1F2A44")
HEADER_FONT = Font(color="FFFFFF", bold=True)


def _header(ws, row, start_col, names):
    for j, n in enumerate(names):
        c = ws.cell(row, start_col + j, n)
        c.fill, c.font = HEADER_FILL, HEADER_FONT


def _make_workbook(path, level):
    wb = Workbook()
    spread = wb.active
    spread.title = "Spread"
    spread["A1"] = f"Demo {level} model - Spread"
    spread["A1"].font = Font(bold=True, size=14)
    tb = wb.create_sheet("TB")
    if level == "L3":
        # mirrors layouts.L3.tb: formulas in A:R, export lands at S
        _header(tb, 1, 1, ["Period", "Key"])
        _header(tb, 1, 19, ["L3_CODE", "PERIOD_END_DATE", "PORTCO_ACCOUNT", "PORTCO_ACCOUNT_DESC",
                            "HFC_ACCOUNT", "PERIODIC_BALANCE", "PERPETUAL_BALANCE"])
        tb["A2"] = '=IF(T2="","",TEXT(T2,"yyyy-mm"))'
        tb["B2"] = '=IF(S2="","",S2&"|"&W2)'
        spread["A3"], spread["B3"] = "Total periodic", "=SUM(TB!X:X)"
    else:
        _header(tb, 1, 1, ["L3_CODE", "PERIOD_END_DATE", "HFC_ACCOUNT", "PERIODIC_BALANCE", "PERPETUAL_BALANCE"])
        spread["A3"], spread["B3"] = "Total periodic", "=SUM(TB!D:D)"
    leg = wb.create_sheet("Legend")
    _header(leg, 1, 1, ["L3_CODE", "L3_NAME", "ENTITY_COUNT"])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def ensure_demo(reset: bool = False) -> None:
    if DEMO_REGISTRY_FILE.exists() and not reset:
        return
    rows = []
    for code, name in DEMO_COMPANIES:
        f = f"L3/{code}_TB (Adjusted TB).xlsx"
        _make_workbook(DEMO_DIR / f, "L3")
        rows.append([f"L3_{code}", "L3", name, code, f, True, ""])
    for gid, gname, rule in [("L2_A", "Group A (prefix rule)", "prefix:A"),
                             ("L2_TRANS", "Transportation (list)", "JEDT, PREM")]:
        f = f"L2/HFC_Model - {gname.split(' (')[0]}.xlsx"
        _make_workbook(DEMO_DIR / f, "L2")
        rows.append([gid, "L2", gname, rule, f, True, ""])
    rows.append(["L3_GONE", "L3", "Sold Co (missing file demo)", "TXBR", "L3/does_not_exist.xlsx", True, ""])
    save_frame(pd.DataFrame(rows, columns=["model_id", "level", "name", "l3_codes", "file_path", "active", "notes"]),
               DEMO_REGISTRY_FILE)
