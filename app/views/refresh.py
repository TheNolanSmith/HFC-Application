import streamlit as st

from core import ui
from core.sources import SqlNotConfigured

ui.header("Refresh models", "Pull the latest TB and Legend exports from Snowflake straight into the workbooks.")

models = ui.models()
if not models:
    st.info("No models registered yet. Add them on the **Models** page.")
    st.stop()

l3s = [m for m in models if m.level == "L3"]
l2s = [m for m in models if m.level == "L2"]
by_id = {m.model_id: m for m in models}

mode = st.radio("Pick models by", ["L2 group", "Hand-pick"], horizontal=True)
selected = []

if mode == "L2 group":
    if not l2s:
        st.info("No L2 models registered.")
        st.stop()
    try:
        fresh, _ = ui.freshness()
    except SqlNotConfigured as e:
        st.warning(str(e))
        st.stop()
    all_codes = fresh["L3_CODE"].tolist()
    g = st.selectbox("L2 group", l2s, format_func=lambda m: f"{m.name}  ({m.l3_codes})")
    codes = set(g.resolve_codes(all_codes))
    members = [m for m in l3s if set(m.resolve_codes(all_codes)) & codes]
    c1, c2 = st.columns(2)
    inc_l3 = c1.checkbox(f"Include its {len(members)} L3 model(s)", value=True)
    inc_l2 = c2.checkbox("Include the L2 itself", value=True)
    selected = (members if inc_l3 else []) + ([g] if inc_l2 else [])
    unregistered = sorted(codes - {c for m in members for c in m.resolve_codes(all_codes)})
    if unregistered:
        st.caption(f"In this group but no L3 model registered: {', '.join(unregistered)}")
else:
    ids = st.multiselect(
        "Models",
        [m.model_id for m in sorted(models, key=lambda m: (m.level != "L3", m.name))],
        format_func=lambda i: f"{by_id[i].level} · {by_id[i].name}",
    )
    selected = [by_id[i] for i in ids]

if selected:
    st.markdown("**Will refresh, in this order:**  " + "  →  ".join(
        f"`{m.level}` {m.name}" for m in sorted(selected, key=lambda m: (m.level != "L3", m.name))))

if st.button(f"Refresh {len(selected)} model(s)", type="primary", disabled=not selected):
    ui.run_refresh(selected)
