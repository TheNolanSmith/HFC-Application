# HFC-Application: engineering notes

Local Streamlit app (Windows, launched from a desktop shortcut) that refreshes L3 / L2 Excel models from Snowflake.

## Layout
- `launcher.py`: run by the desktop shortcut through `.venv\Scripts\pythonw.exe`. Starts Streamlit on port 8517 if it isn't already running, then opens the browser.
- `app/Home.py`: entry point. Sets up `st.navigation` over `app/views/*`.
- `app/core/`
  - `config.py`: loads settings (`settings.example.yaml` merged under `settings.yaml`). Defines `SheetLayout`.
  - `registry.py`: `config/models.csv`, one row per workbook. L2 `l3_codes` takes `prefix:X` or a list.
  - `sources.py`: `SnowflakeSource` and `DemoSource`, both exposing the same `freshness()` / `export()`. SQL lives in `sql/*.sql` and is bound with `%(l3_codes)s`, which the connector expands from a tuple. Any `<<placeholder>>` raises `SqlNotConfigured`.
  - `excel_writer.py`: `XlwingsWriter` for real runs, `OpenpyxlWriter` for demo mode and tests. On any error the workbook is closed without saving.
  - `refresh.py`: orchestration. Order is L3s then L2s, with one Excel instance per batch. Backup, then export, then write, then log.
  - `refresh_log.py`: always writes to local SQLite (`data/refresh_log.db`); also writes to the Snowflake table if configured. Never raises.
  - `status.py`: board statuses (Missing file, No data, Never refreshed, New period, Updated data, Current).
- `data/` is git-ignored: local log, demo workbooks, app.log.

## Rules
- Never change the user's workbook headers or formats. Only the data block and the formula fill-down.
- Don't hold the TB in heavy formulas. Large TBs (200k+ rows) freeze Excel. Bulk value writes only.
- xlwings runs on Streamlit worker threads, so `pythoncom.CoInitialize()` is required (handled in `XlwingsWriter.__enter__`).
- Git: the user runs git commands himself in PowerShell. Don't run git on his machine through the device bridge.
- Tests: `python -m pytest tests` (pytest isn't on his PATH).
