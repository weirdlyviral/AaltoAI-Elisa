"""Trade-off Explorer — human in the loop. Owner: TBD.

Sliders for k, time bucket, area mode and epsilon over the precomputed grid
(python -m src.tradeoff, M6.2) show the matched config's risk and utility,
a scatter of every config, and an "Approve release" action that appends to
outputs/release_decisions.jsonl. Detail lives in docs/specs/m6.md (6.2).
"""
import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import streamlit as st

from lib import components, data, theme

theme.setup_page("Trade-off Explorer", icon="🎛️")
st.caption("Owner: TBD")
st.write(
    "Sliders for k, time bucket, area mode and epsilon walk the precomputed "
    "grid and show the matched config's risk (three criteria) and utility, "
    "plus a scatter of every config with the deployed one marked. Not built "
    "yet beyond this plumbing check — see docs/specs/m6.md §6.2."
)

grid, is_mock = data.load_tradeoff_grid()

if grid is None:
    components.pending("trade-off grid (outputs/tradeoff_grid.json)")
else:
    if is_mock:
        st.warning(
            "⚠️ MOCK DATA — outputs/tradeoff_grid.json does not exist yet "
            "(built by `python -m src.tradeoff` in M6.2). The numbers below "
            "are fabricated placeholders from app/lib/mock_tradeoff_grid.json."
        )

    ks = sorted({entry["config"]["k"] for entry in grid})
    time_buckets = sorted({entry["config"]["time_bucket"] for entry in grid})
    area_modes = sorted({entry["config"]["area_mode"] for entry in grid})
    epsilons = sorted(
        {entry["config"]["epsilon"] for entry in grid if entry["config"]["epsilon"] is not None}
    )

    col1, col2, col3, col4 = st.columns(4)
    selected_k = col1.select_slider("k", options=ks)
    selected_time_bucket = col2.select_slider("time bucket (min)", options=time_buckets)
    selected_area_mode = col3.selectbox("area mode", options=area_modes)
    selected_epsilon = col4.select_slider("epsilon", options=epsilons)

    match = next(
        (
            entry
            for entry in grid
            if entry["config"]["k"] == selected_k
            and entry["config"]["time_bucket"] == selected_time_bucket
            and entry["config"]["area_mode"] == selected_area_mode
            and entry["config"]["epsilon"] == selected_epsilon
        ),
        None,
    )

    if match is None:
        components.pending("a grid entry for this exact combination")
    else:
        st.subheader("Criteria (contextual approach)")
        badge_cols = st.columns(len(match["criteria"]))
        for col, (criterion_key, status) in zip(badge_cols, match["criteria"].items()):
            with col:
                label = data.GRID_CRITERION_LABELS.get(criterion_key, criterion_key)
                components.criterion_badge(label, status)

        st.subheader("Metrics")
        st.json(match["metrics"])

        if match["releasable"]:
            st.success("✅ Releasable under the contextual approach")
        else:
            st.error("🚫 Not releasable — at least one criterion fails")
