"""HFC Model Refresh - entry point. Launched by launcher.py (desktop icon)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st  # noqa: E402

from core import ui  # noqa: E402

st.set_page_config(page_title="HFC Model Refresh", page_icon="🔄", layout="wide")

pages = [
    st.Page("views/status.py", title="Status board", icon="🚦", default=True),
    st.Page("views/refresh.py", title="Refresh models", icon="🔄"),
    st.Page("views/run_log.py", title="Run log", icon="🧾"),
    st.Page("views/models.py", title="Models", icon="🗂️"),
    st.Page("views/settings.py", title="Settings", icon="⚙️"),
]
nav = st.navigation(pages)
ui.sidebar()
nav.run()
