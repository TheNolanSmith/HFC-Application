import pandas as pd
import streamlit as st

from core import ui

ui.header("Run log", "Every refresh — who, when, what period, how many rows.")

log, where = ui.refresh_log().read()
st.caption(f"Source: {where}" + ("" if where == "Snowflake" else " (Snowflake log not configured or unreachable)"))
if log.empty:
    st.info("No refreshes yet.")
    st.stop()

c1, c2, c3 = st.columns(3)
model = c1.multiselect("Model", sorted(log["MODEL_NAME"].dropna().unique()))
stat = c2.multiselect("Status", ["SUCCESS", "FAILED"])
user = c3.multiselect("User", sorted(log["USER_NAME"].dropna().unique()))
v = log
if model:
    v = v[v["MODEL_NAME"].isin(model)]
if stat:
    v = v[v["STATUS"].isin(stat)]
if user:
    v = v[v["USER_NAME"].isin(user)]

v = v.assign(**{"": v["STATUS"].map({"SUCCESS": "✅", "FAILED": "❌"})})
st.dataframe(
    v[["", "STARTED_AT", "MODEL_NAME", "LEVEL", "THROUGH_PERIOD", "TB_ROWS", "LEGEND_ROWS", "SECONDS",
       "USER_NAME", "MESSAGE", "L3_CODES", "FILE_PATH", "BATCH_ID", "RUN_ID"]],
    hide_index=True,
    width="stretch",
    column_config={
        "STARTED_AT": st.column_config.DatetimeColumn("Started", format="MMM D YYYY, h:mm a"),
        "MODEL_NAME": "Model", "LEVEL": "Level",
        "THROUGH_PERIOD": st.column_config.DateColumn("Through", format="MMM YYYY"),
        "TB_ROWS": st.column_config.NumberColumn("TB rows", format="%d"),
        "LEGEND_ROWS": st.column_config.NumberColumn("Legend rows", format="%d"),
        "SECONDS": "Sec", "USER_NAME": "User", "MESSAGE": "Message",
    },
)
st.download_button("Download CSV", v.drop(columns=[""]).to_csv(index=False), "refresh_log.csv", "text/csv")
