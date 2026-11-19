import pandas as pd
import streamlit as st

from core import config, status, ui
from core.sources import SqlNotConfigured

ui.header("Status board", "Which L3 and L2 models are behind what's in Snowflake.")

s = ui.settings()
models = ui.models()
if not models:
    st.info("No models registered yet. Add them on the **Models** page.")
    st.stop()

c1, c2 = st.columns([1, 5])
force = c1.button("↻ Check now", help="Re-query Snowflake (otherwise cached for 5 minutes)")
try:
    fresh, checked = ui.freshness(force=force)
except SqlNotConfigured as e:
    st.warning(str(e))
    st.stop()
except Exception as e:
    st.error(f"Couldn't reach Snowflake: {e}")
    st.caption("Check the Settings page → Test connection.")
    st.stop()
c2.caption(f"Snowflake checked {checked:%I:%M %p} · log from {ui.refresh_log().read()[1]}")

board = status.board(models, fresh, ui.refresh_log().last_success(), config.models_root(s))
stale = board[board["Status"].isin(status.NEEDS_REFRESH)]
problems = board[board["Status"].isin(["Missing file", "No data"])]

m1, m2, m3, m4 = st.columns(4)
m1.metric("Need refresh", len(stale))
m2.metric("Current", int((board["Status"] == "Current").sum()))
m3.metric("Problems", len(problems))
m4.metric("Latest period in Snowflake", f"{fresh['LATEST_PERIOD'].max():%b %Y}" if len(fresh) else "—")

f1, f2 = st.columns([1, 3])
level = f1.segmented_control("Level", ["All", "L3", "L2"], default="All")
pick = f2.multiselect("Status", status.STATUS_ORDER, default=[])
view = board.copy()
if level and level != "All":
    view = view[view["Level"] == level]
if pick:
    view = view[view["Status"].isin(pick)]

view.insert(0, "Select", view["Status"].isin(status.NEEDS_REFRESH))
edited = st.data_editor(
    view,
    hide_index=True,
    width="stretch",
    disabled=[c for c in view.columns if c != "Select"],
    column_config={
        "Select": st.column_config.CheckboxColumn(width="small"),
        "": st.column_config.TextColumn(width="small"),
        "model_id": None,
        "File": None,
        "Data through": st.column_config.DateColumn(format="MMM YYYY"),
        "Lagging co. through": st.column_config.DateColumn(format="MMM YYYY",
                                                           help="L2 only: the least-current company in the group"),
        "Model through": st.column_config.DateColumn(format="MMM YYYY"),
        "Data changed": st.column_config.DatetimeColumn(format="MMM D, h:mm a"),
        "Last refreshed": st.column_config.DatetimeColumn(format="MMM D, h:mm a"),
    },
    key=f"board_{level}_{'-'.join(pick)}",
)

chosen_ids = edited.loc[edited["Select"], "model_id"].tolist()
by_id = {m.model_id: m for m in models}
chosen = [by_id[i] for i in chosen_ids if board.set_index("model_id").loc[i, "Status"] != "Missing file"]

b1, b2 = st.columns([1, 4])
go = b1.button(f"Refresh {len(chosen)} selected", type="primary", disabled=not chosen)
b2.caption("Ticked by default: everything that needs a refresh. L3s run before L2s. "
           "Each file is backed up before it's written.")
if go:
    ui.run_refresh(chosen)
    st.button("Update board")

with st.expander("What the statuses mean"):
    st.markdown(
        """
- 🔴 **New period** — Snowflake has a later month than the model was last refreshed through.
- 🟠 **Updated data** — same month, but the company's data changed in Snowflake after the last refresh (restatement, late JE, re-load).
- 🆕 **Never refreshed** — no successful run in the log yet.
- 🟢 **Current** — nothing new since the last refresh.
- ⚠️ **No data** — none of the model's L3 codes are in the freshness query.
- ⛔ **Missing file** — the workbook isn't at the path in the Models page (SharePoint not synced, or moved).
"""
    )
