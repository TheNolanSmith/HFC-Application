"""Shared Streamlit plumbing: settings/source/log singletons, styling, the refresh runner."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime

import pandas as pd
import streamlit as st

from . import config, demo, registry
from .refresh import refresh_models
from .refresh_log import RefreshLog
from .sources import DemoSource, SnowflakeSource

GOLD = "#B8955A"

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"], .stMarkdown, .stDataFrame, button, input, textarea { font-family: 'Inter', sans-serif; }
[data-testid="stSidebar"] { background: #1C2230; }
[data-testid="stSidebar"] p, [data-testid="stSidebar"] span, [data-testid="stSidebar"] h3,
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] { color: #E6E8EE; }
[data-testid="stSidebar"] button[data-testid^="stBaseButton"] { background: transparent !important; border: 1px solid #4B5263 !important; }
[data-testid="stSidebar"] .stButton > button p { color: #E6E8EE; }
[data-testid="stSidebar"] [data-testid="stSidebarNavLink"][aria-current="page"] { background: rgba(184,149,90,.18); border-left: 3px solid #B8955A; }
.block-container { padding-top: 2.2rem; max-width: 1400px; }
h1 { font-weight: 700; letter-spacing: -.02em; }
.hfc-sub { color: #6B7280; margin-top: -.6rem; margin-bottom: 1.2rem; }
.hfc-pill { display:inline-block; padding:2px 10px; border-radius:999px; font-size:.78rem; font-weight:600; }
[data-testid="stSidebar"] span.hfc-demo, .hfc-demo { background:#FEF3C7; color:#92400E; }
[data-testid="stSidebar"] span.hfc-live, .hfc-live { background:#DCFCE7; color:#166534; }
[data-testid="stMetric"] { background:#fff; border:1px solid #E5E7EB; border-radius:10px; padding:14px 16px; }
[data-testid="stMetricValue"] { font-weight:700; }
</style>
"""


def header(title: str, sub: str = "") -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.title(title)
    if sub:
        st.markdown(f'<div class="hfc-sub">{sub}</div>', unsafe_allow_html=True)


# --------------------------------------------------------------------------- state
def settings() -> dict:
    if "settings" not in st.session_state:
        st.session_state.settings = config.load_settings()
    return st.session_state.settings


def reload_settings() -> None:
    st.session_state.pop("settings", None)
    st.cache_resource.clear()
    st.cache_data.clear()


@st.cache_resource(show_spinner=False)
def _source(demo_mode: bool, sf_json: str):
    if demo_mode:
        demo.ensure_demo()
        return DemoSource()
    return SnowflakeSource(json.loads(sf_json))


def source():
    s = settings()
    return _source(bool(s.get("demo_mode")), json.dumps(s.get("snowflake", {}), sort_keys=True))


def refresh_log() -> RefreshLog:
    key = "refresh_log_obj"
    if key not in st.session_state or st.session_state.get("_log_src") is not source():
        st.session_state[key] = RefreshLog(settings(), source())
        st.session_state["_log_src"] = source()
    return st.session_state[key]


def models(active_only: bool = True) -> list[registry.Model]:
    if settings().get("demo_mode"):
        demo.ensure_demo()
    return registry.load_models(registry.registry_file(settings()), active_only=active_only)


@st.cache_data(ttl=300, show_spinner="Checking Snowflake for new data…")
def _freshness(_src, key: str) -> tuple[pd.DataFrame, datetime]:
    return _src.freshness(), datetime.now()


def freshness(force: bool = False) -> tuple[pd.DataFrame, datetime]:
    if force:
        _freshness.clear()
    s = settings()
    return _freshness(source(), f"{s.get('demo_mode')}|{json.dumps(s.get('snowflake', {}), sort_keys=True)}")


# --------------------------------------------------------------------------- sidebar
def sidebar() -> None:
    s = settings()
    with st.sidebar:
        st.markdown(f"### <span style='color:{GOLD}'>HFC</span> Model Refresh", unsafe_allow_html=True)
        if s.get("demo_mode"):
            st.markdown('<span class="hfc-pill hfc-demo">DEMO MODE</span>', unsafe_allow_html=True)
            st.caption("Fake data + sample workbooks. Turn off on the Settings page.")
        else:
            sf = s.get("snowflake", {})
            st.markdown('<span class="hfc-pill hfc-live">SNOWFLAKE</span>', unsafe_allow_html=True)
            st.caption(f"{sf.get('account') or '—'} · {sf.get('role') or 'default role'}")
        st.caption(f"v{config.APP_VERSION}")
        st.divider()
        if st.button("Quit app", width="stretch", help="Stops the background server. Reopen from the desktop icon."):
            st.success("Shutting down — you can close this tab.")
            try:
                source().close()
            except Exception:
                pass
            threading.Timer(1.0, lambda: os._exit(0)).start()
            st.stop()


# --------------------------------------------------------------------------- runner
def run_refresh(selected: list[registry.Model]) -> None:
    if not selected:
        st.warning("Nothing selected.")
        return
    s = settings()
    lines: list[str] = []
    box = st.status(f"Refreshing {len(selected)} model(s)…", expanded=True)
    with box:
        log_area = st.empty()
        prog = st.progress(0.0)
        done = {"n": 0}

        def log(msg: str) -> None:
            lines.append(f"{datetime.now():%H:%M:%S}  {msg}")
            log_area.code("\n".join(lines[-40:]), language=None)

        def on_done(_res) -> None:
            done["n"] += 1
            prog.progress(done["n"] / len(selected))

        try:
            fresh, _ = freshness()
            results = refresh_models(selected, s, source(), refresh_log(), fresh=fresh, log=log, on_done=on_done)
        except Exception as e:
            box.update(label=f"Refresh stopped: {e}", state="error")
            st.exception(e)
            return
    ok = sum(r.ok for r in results)
    failed = len(results) - ok
    box.update(
        label=f"Done — {ok} refreshed" + (f", {failed} failed" if failed else ""),
        state="complete" if not failed else "error",
        expanded=bool(failed),
    )
    st.dataframe(
        pd.DataFrame(
            [{
                "": "✅" if r.ok else "❌",
                "Model": r.model.name,
                "Level": r.model.level,
                "TB rows": r.record.TB_ROWS,
                "Legend rows": r.record.LEGEND_ROWS,
                "Through": r.record.THROUGH_PERIOD,
                "Seconds": r.record.SECONDS,
                "Message": r.record.MESSAGE,
            } for r in results]
        ),
        hide_index=True,
        width="stretch",
    )
    if refresh_log().last_remote_error:
        st.info(f"Logged on this PC only — Snowflake log write failed: {refresh_log().last_remote_error}")
    st.session_state["last_results"] = results
