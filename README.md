# HFC Model Refresh

Desktop app for coordinating L3 / L2 model updates from Snowflake.

- **Status board**: every registered model, flagged when Snowflake has a newer period or changed data since its last refresh.
- **Refresh**: pulls the TB (and Legend) export and writes it straight into the workbook. Pick models one at a time, by hand, or as an L2 group (its L3s, then the L2).
- **Run log**: who refreshed what, when, through which period, with row counts. Written to Snowflake for the team and to this PC as a fallback.
- **Safety**: each file is backed up before it's written. A run that fails is never saved. A TB export that returns 0 rows is refused. Files that are open in Excel are skipped.

## Install (one time)

1. Put this folder somewhere local, e.g. `C:\Users\nsmith\Projects\HFC-Application`. Don't put it in SharePoint or OneDrive.
2. In PowerShell, from that folder, run:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\install.ps1
   ```
3. Double-click **HFC Model Refresh** on your desktop. It opens in your browser in **demo mode**, with fake data and sample workbooks, so you can click through everything safely.

## Go live

1. **Settings page**: enter the Snowflake account, user, role and warehouse. SSO is the default sign-in. Set **Models root** to your synced SharePoint folder. Click **Save**, then **Test connection**.
2. **`sql/` folder**: paste your real queries over the `<<placeholders>>`:
   | File | What it returns |
   |---|---|
   | `freshness.sql` | One row per L3: `L3_CODE, L3_NAME, LATEST_PERIOD, LAST_LOADED_AT` |
   | `L3_tb.sql` / `L2_tb.sql` | The TB export, columns in TB-sheet order, filtered `WHERE L3_CODE IN %(l3_codes)s` |
   | `L3_legend.sql` / `L2_legend.sql` | Legend export. Delete the file if a level has no Legend. |
   The Settings page shows which files are ready.
3. **Settings → Workbook layouts**: confirm the sheet name, header row, first data column and formula columns for the L3 and L2 TB and Legend sheets. Formula columns are filled down from the first data row to the new last row.
4. **Models page**: add each L3 and L2 workbook. Use **Scan** to list the files under models root. For an L2, set `l3_codes` to `prefix:A`, or to a list like `ARCH, JEDT`.
5. Turn off **Demo mode** and save.

## How writing works

The app uses xlwings to run a private, hidden copy of Excel, so pivots, slicers, named ranges and macros stay intact. It works in this order:

1. Turns calculation to manual.
2. Clears the old data block. Values only; headers and formats are left alone.
3. Writes the new data in 50k-row chunks.
4. Fills the formula columns down.
5. Resizes the Excel Table, if you set one.
6. Runs RefreshAll and recalculates.
7. Saves.

## Updating

Pull the latest code, then re-run `install.ps1`. It never overwrites `config\settings.yaml`.

## Tests

```powershell
.venv\Scripts\python -m pytest tests
```
