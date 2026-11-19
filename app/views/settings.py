import copy

import streamlit as st
import yaml

from core import config, demo, sources, ui

ui.header("Settings", "Snowflake connection, SQL readiness, and where data lands in each workbook.")

s = copy.deepcopy(ui.settings())
sf = s.setdefault("snowflake", {})
paths = s.setdefault("paths", {})

st.subheader("Mode")
s["demo_mode"] = st.toggle("Demo mode (fake data, sample workbooks)", value=bool(s.get("demo_mode")))

st.subheader("Snowflake")
c1, c2 = st.columns(2)
sf["account"] = c1.text_input("Account", sf.get("account", ""), help="e.g. abc12345.us-east-1 or orgname-acctname")
sf["user"] = c2.text_input("User", sf.get("user", ""))
auths = ["externalbrowser", "snowflake_jwt", "snowflake"]
sf["authenticator"] = c1.selectbox(
    "Sign-in method", auths, index=auths.index(sf.get("authenticator", "externalbrowser")),
    format_func={"externalbrowser": "SSO (browser pop-up)", "snowflake_jwt": "Key pair",
                 "snowflake": "Password (SNOWFLAKE_PASSWORD env var)"}.get,
)
if sf["authenticator"] == "snowflake_jwt":
    sf["private_key_file"] = c2.text_input("Private key file (.p8)", sf.get("private_key_file", ""))
sf["role"] = c1.text_input("Role", sf.get("role", ""))
sf["warehouse"] = c2.text_input("Warehouse", sf.get("warehouse", ""))
sf["database"] = c1.text_input("Database", sf.get("database", "HFC_DATA"))
sf["schema"] = c2.text_input("Schema", sf.get("schema", "MARTS"))

st.subheader("Files")
paths["models_root"] = st.text_input(
    "Models root (SharePoint synced folder)", paths.get("models_root", ""),
    help="Copy the folder path from File Explorer's address bar.",
)
c1, c2 = st.columns([3, 1])
paths["backups_dir"] = c1.text_input("Backups folder", paths.get("backups_dir", ""))
paths["keep_backups"] = c2.number_input("Keep per model", 1, 50, int(paths.get("keep_backups", 5)))
s.setdefault("logging", {})["snowflake_table"] = st.text_input(
    "Team refresh log table (blank = this PC only)", s["logging"].get("snowflake_table", ""))

with st.expander("Workbook layouts (where each export lands)"):
    st.caption("sheet · header_row · data_start_col · formula_cols (filled down) · table_name (optional Excel Table)")
    txt = st.text_area("layouts", yaml.safe_dump(s.get("layouts", {}), sort_keys=False), height=420,
                       label_visibility="collapsed")
    try:
        s["layouts"] = yaml.safe_load(txt)
    except yaml.YAMLError as e:
        st.error(f"Layout YAML error: {e}")

b1, b2, b3, _ = st.columns([1, 1, 1.4, 2])
if b1.button("Save", type="primary"):
    config.save_settings(s)
    ui.reload_settings()
    st.success(f"Saved to {config.SETTINGS_FILE}")
    st.rerun()
if b2.button("Test connection"):
    try:
        with st.spinner("Connecting… (SSO opens a browser tab the first time)"):
            who = ui.source().whoami()
        st.success(f"Connected as {who.get('U')} · role {who.get('R')} · warehouse {who.get('W')}")
    except Exception as e:
        st.error(f"Connection failed: {e}")
if s.get("demo_mode") and b3.button("Reset demo workbooks"):
    demo.ensure_demo(reset=True)
    st.success("Demo workbooks rebuilt.")
st.caption("Test connection uses the *saved* settings — Save first.")

st.subheader("SQL files")
st.caption(f"Folder: `{config.SQL_DIR}` — paste your queries in, replacing the <<placeholders>>.")
icon = {"ready": "✅ ready", "placeholder": "✏️ needs your query", "missing": "➖ not used (file deleted)"}
st.table({"File": [f"{k}.sql" for k in sources.sql_status()],
          "Status": [icon[v] for v in sources.sql_status().values()]})
