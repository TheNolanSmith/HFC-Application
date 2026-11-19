"""Write query results into model workbooks.

XlwingsWriter (default, Windows): drives a private, hidden Excel instance, so pivots,
slicers, named ranges and macros survive untouched. Data goes in as bulk value
writes in chunks; formula columns are extended with Excel's own FillDown; pivots
are refreshed with RefreshAll before saving.

OpenpyxlWriter: pure-Python fallback used by demo mode and the tests. It keeps
formulas, tables and VBA, but can't recalculate - pivots are flagged to refresh
the next time someone opens the file.

Both: if anything fails, the workbook is closed WITHOUT saving, so the file on
disk is never left half-written (and a backup is taken before every run anyway).
"""
from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
from openpyxl.utils import column_index_from_string, get_column_letter

from .config import SheetLayout


class WorkbookLocked(RuntimeError):
    pass


def assert_not_open(path: Path) -> None:
    """Excel drops an owner file (~$Name.xlsx) next to a workbook while it's open on
    this PC. For long names it trims the first one or two characters, so check all three."""
    name = path.name
    if any(path.with_name("~$" + name[k:]).exists() for k in (0, 1, 2)):
        raise WorkbookLocked(f"{name} is open in Excel on this PC. Close it and retry.")


def _flat(v) -> list:
    if isinstance(v, (list, tuple)):
        return [x for item in v for x in _flat(item)]
    return [v]


def col_range(spec: str) -> tuple[int, int] | None:
    """'A:R' -> (1, 18); '' -> None."""
    spec = (spec or "").strip().upper()
    if not spec:
        return None
    a, _, b = spec.partition(":")
    a_i = column_index_from_string(a)
    b_i = column_index_from_string(b or a)
    return (min(a_i, b_i), max(a_i, b_i))


def _cell(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if v is pd.NaT or (not isinstance(v, (str, bytes)) and pd.isna(v) is True):
        return None
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    if isinstance(v, Decimal):
        return float(v)
    if hasattr(v, "item"):  # numpy scalar
        return v.item()
    return v


def to_rows(df: pd.DataFrame) -> list[list]:
    return [[_cell(v) for v in row] for row in df.itertuples(index=False, name=None)]


# --------------------------------------------------------------------------- xlwings
class XlwingsWriter:
    def __init__(self, chunk_rows: int = 50000, visible: bool = False):
        self.chunk_rows = max(1000, int(chunk_rows))
        self.visible = visible
        self.app = None

    def __enter__(self):
        import xlwings as xw  # Windows/mac only; imported lazily so tests run anywhere

        try:  # Streamlit runs scripts on worker threads; COM needs initialising per thread
            import pythoncom

            pythoncom.CoInitialize()
        except ImportError:
            pass
        self.app = xw.App(visible=self.visible, add_book=False)
        self.app.display_alerts = False
        self.app.screen_updating = self.visible
        try:
            self.app.enable_events = False  # don't fire Workbook_Open / change macros
        except Exception:
            pass
        return self

    def __exit__(self, *exc):
        if self.app is not None:
            try:
                for b in list(self.app.books):
                    b.close()
            finally:
                self.app.quit()
                self.app = None
                try:
                    import pythoncom

                    pythoncom.CoUninitialize()
                except ImportError:
                    pass

    def write(self, path: Path, frames: dict[str, tuple[SheetLayout, pd.DataFrame]], log=print) -> dict[str, int]:
        assert_not_open(path)
        wb = self.app.books.open(str(path), update_links=False)
        try:
            if wb.api.ReadOnly:
                raise WorkbookLocked(f"{path.name} opened read-only - someone else probably has it open.")
            self.app.calculation = "manual"
            counts = {}
            for section, (layout, df) in frames.items():
                log(f"Writing {len(df):,} rows to '{layout.sheet}'")
                counts[section] = self._write_sheet(wb.sheets[layout.sheet], layout, df, log)
            log("Refreshing pivots / queries")
            wb.api.RefreshAll()
            try:
                self.app.api.CalculateUntilAsyncQueriesDone()
            except Exception:
                pass
            self.app.calculation = "automatic"
            self.app.calculate()
            log("Saving")
            wb.save()
            return counts
        finally:
            wb.close()

    def _write_sheet(self, sh, lay: SheetLayout, df: pd.DataFrame, log) -> int:
        first = lay.first_data_row
        start = column_index_from_string(lay.data_start_col)
        n, ncols = len(df), max(len(df.columns), 1)
        last_old = sh.used_range.last_cell.row
        fcols = col_range(lay.formula_cols)

        # 1. clear old data block (values only - formats and headers untouched)
        if last_old >= first:
            sh.range((first, start), (last_old, start + ncols - 1)).clear_contents()

        # 2. bulk write in chunks
        rows = to_rows(df)
        for i in range(0, n, self.chunk_rows):
            sh.range((first + i, start)).value = rows[i : i + self.chunk_rows]

        # 3. formula columns: first data row is the template; FillDown to the new last row
        if fcols:
            a, b = fcols
            template = sh.range((first, a), (first, b))
            if not any(str(f).startswith("=") for f in _flat(template.formula)):
                log(f"Warning: no formulas found in {lay.formula_cols}{first} - nothing to fill down")
            elif n > 1:
                sh.range((first, a), (first + n - 1, b)).api.FillDown()
            if last_old >= first + max(n, 1):
                sh.range((first + max(n, 1), a), (last_old, b)).clear_contents()

        # 4. optional Excel Table resize
        if lay.table_name:
            lo = sh.api.ListObjects(lay.table_name)
            left = lo.Range.Column
            right = left + lo.Range.Columns.Count - 1
            lo.Resize(sh.range((lay.header_row, left), (lay.header_row + max(n, 1), right)).api)
        return n


# --------------------------------------------------------------------------- openpyxl
class OpenpyxlWriter:
    def __init__(self, **_):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def write(self, path: Path, frames: dict[str, tuple[SheetLayout, pd.DataFrame]], log=print) -> dict[str, int]:
        from openpyxl import load_workbook

        assert_not_open(path)
        wb = load_workbook(path, keep_vba=path.suffix.lower() == ".xlsm")
        counts = {}
        for section, (layout, df) in frames.items():
            log(f"Writing {len(df):,} rows to '{layout.sheet}'")
            counts[section] = self._write_sheet(wb[layout.sheet], layout, df)
        for ws in wb.worksheets:
            for pv in getattr(ws, "_pivots", []):
                pv.cache.refreshOnLoad = True
        log("Saving")
        wb.save(path)
        return counts

    def _write_sheet(self, ws, lay: SheetLayout, df: pd.DataFrame) -> int:
        from openpyxl.formula.translate import Translator

        first = lay.first_data_row
        start = column_index_from_string(lay.data_start_col)
        n, ncols = len(df), max(len(df.columns), 1)
        last_old = ws.max_row
        fcols = col_range(lay.formula_cols)

        for r in range(first, last_old + 1):
            for c in range(start, start + ncols):
                ws.cell(r, c).value = None
        for i, row in enumerate(to_rows(df)):
            for j, v in enumerate(row):
                ws.cell(first + i, start + j).value = v

        if fcols:
            a, b = fcols
            for c in range(a, b + 1):
                tmpl = ws.cell(first, c).value
                origin = f"{get_column_letter(c)}{first}"
                for r in range(first + 1, max(last_old, first + n - 1) + 1):
                    if r < first + n and isinstance(tmpl, str) and tmpl.startswith("="):
                        ws.cell(r, c).value = Translator(tmpl, origin=origin).translate_formula(f"{get_column_letter(c)}{r}")
                    elif r >= first + max(n, 1):
                        ws.cell(r, c).value = None

        if lay.table_name and lay.table_name in ws.tables:
            t = ws.tables[lay.table_name]
            left_right = t.ref.split(":")
            left = "".join(ch for ch in left_right[0] if ch.isalpha())
            right = "".join(ch for ch in left_right[1] if ch.isalpha())
            t.ref = f"{left}{lay.header_row}:{right}{lay.header_row + max(n, 1)}"
        return n


def make_writer(settings: dict):
    xl = settings.get("excel", {})
    engine = "openpyxl" if settings.get("demo_mode") else (xl.get("engine") or "xlwings").lower()
    cls = XlwingsWriter if engine == "xlwings" else OpenpyxlWriter
    return cls(chunk_rows=xl.get("chunk_rows", 50000), visible=bool(xl.get("visible")))
