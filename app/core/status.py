"""Which models are stale: compare Snowflake freshness with each model's last successful refresh."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .registry import Model

# Ordered most- to least-urgent; the board sorts by this.
STATUS_ORDER = ["Missing file", "No data", "Never refreshed", "New period", "Updated data", "Current"]
STATUS_ICON = {
    "Missing file": "⛔",
    "No data": "⚠️",
    "Never refreshed": "🆕",
    "New period": "🔴",
    "Updated data": "🟠",
    "Current": "🟢",
}
NEEDS_REFRESH = {"Never refreshed", "New period", "Updated data"}


def model_status(model: Model, fresh: pd.DataFrame, last_ok: pd.DataFrame, root: Path) -> dict:
    all_codes = fresh["L3_CODE"].tolist()
    codes = model.resolve_codes(all_codes)
    sub = fresh[fresh["L3_CODE"].isin(codes)]
    missing_codes = sorted(set(codes) - set(sub["L3_CODE"]))
    path = model.resolve_file(root)

    latest_period = sub["LATEST_PERIOD"].max() if len(sub) else None
    latest_load = sub["LAST_LOADED_AT"].max() if len(sub) else None
    # An L2 is only as current as its slowest company.
    lagging_period = sub["LATEST_PERIOD"].min() if len(sub) else None

    prev = last_ok.loc[model.model_id] if model.model_id in last_ok.index else None
    through = prev["THROUGH_PERIOD"] if prev is not None else None
    snap = prev["DATA_LOADED_AT"] if prev is not None else None

    if not path.exists():
        status = "Missing file"
    elif sub.empty:
        status = "No data"
    elif prev is None:
        status = "Never refreshed"
    elif through is None or pd.isna(through) or latest_period > through:
        status = "New period"
    elif snap is None or pd.isna(snap) or latest_load > snap:
        status = "Updated data"
    else:
        status = "Current"

    return {
        "": STATUS_ICON[status],
        "Status": status,
        "Level": model.level,
        "Model": model.name,
        "model_id": model.model_id,
        "L3 codes": len(codes) if model.level == "L2" else ", ".join(codes),
        "Data through": latest_period,
        "Lagging co. through": lagging_period if model.level == "L2" else None,
        "Model through": through,
        "Data changed": latest_load,
        "Last refreshed": prev["FINISHED_AT"] if prev is not None else None,
        "Refreshed by": prev["USER_NAME"] if prev is not None else None,
        "Missing codes": ", ".join(missing_codes),
        "File": str(path),
    }


def board(models: list[Model], fresh: pd.DataFrame, last_ok: pd.DataFrame, root: Path) -> pd.DataFrame:
    rows = [model_status(m, fresh, last_ok, root) for m in models]
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["_o"] = df["Status"].map(STATUS_ORDER.index)
    df["_l"] = df["Level"].map({"L3": 0, "L2": 1})
    for c in ("Data through", "Lagging co. through", "Model through", "Data changed", "Last refreshed"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    df["Refreshed by"] = df["Refreshed by"].fillna("")
    return df.sort_values(["_o", "_l", "Model"]).drop(columns=["_o", "_l"]).reset_index(drop=True)
