import pandas as pd
import streamlit as st

from core import config, registry, ui

ui.header("Models", "The workbooks the app manages. Edit in place, then Save.")

s = ui.settings()
ui.models()  # builds demo registry on first run in demo mode
path = registry.registry_file(s)
root = config.models_root(s)
st.caption(f"Registry: `{path}` · relative file paths resolve under `{root}`")

df = registry.load_frame(path)
edited = st.data_editor(
    df,
    num_rows="dynamic",
    hide_index=True,
    width="stretch",
    column_config={
        "model_id": st.column_config.TextColumn("model_id", help="Short unique key, e.g. L3_ARCH. Don't rename once used — the log keys on it."),
        "level": st.column_config.SelectboxColumn("level", options=list(config.LEVELS), required=True),
        "name": "Display name",
        "l3_codes": st.column_config.TextColumn("l3_codes", help="L3: one code.  L2: prefix:A  or  ARCH, JEDT, DOON"),
        "file_path": st.column_config.TextColumn("file_path", width="large", help="Relative to models_root, or a full path"),
        "active": st.column_config.CheckboxColumn("active", default=True),
        "notes": "Notes",
    },
    key="registry_editor",
)

errors = registry.validate(edited.fillna("")) if len(edited) else []
for e in errors:
    st.error(e)

c1, c2, _ = st.columns([1, 1, 4])
if c1.button("Save", type="primary", disabled=bool(errors)):
    registry.save_frame(edited.fillna(""), path)
    st.success(f"Saved {len(edited)} model(s).")
missing = [r.file_path for r in edited.itertuples() if r.file_path and not registry.Model("", "", "", "", str(r.file_path)).resolve_file(root).exists()]
if missing:
    st.warning("Files not found:\n\n" + "\n".join(f"- `{m}`" for m in missing))

with st.expander("Bulk add: scan a folder for workbooks"):
    st.caption("Lists .xlsx / .xlsm files under models_root so you can paste rows instead of typing paths.")
    sub = st.text_input("Sub-folder of models_root (blank = all)", "")
    if st.button("Scan"):
        base = root / sub if sub else root
        files = sorted(p for ext in ("*.xlsx", "*.xlsm") for p in base.rglob(ext) if not p.name.startswith("~$"))
        known = set(edited["file_path"].astype(str))
        rows = [{"file_path": str(p.relative_to(root)) if p.is_relative_to(root) else str(p)} for p in files]
        rows = [r for r in rows if r["file_path"] not in known]
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            st.caption(f"{len(rows)} not yet registered.")
        else:
            st.info("Nothing new found.")
