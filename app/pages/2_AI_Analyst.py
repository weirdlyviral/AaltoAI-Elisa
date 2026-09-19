"""AI Analyst — Mistral-backed Q&A over the aggregate release. Owner: TBD.

Full tool-calling loop (safety.llm_gateway, max 6 steps, query_aggregate as
the only data tool) is a stretch goal (M6.3) and is not built yet. This page
wires and proves query_aggregate itself, which is implemented fully.
Detail lives in docs/specs/m6.md (6.3).
"""
import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import streamlit as st

from lib import agent, theme

theme.setup_page("AI Analyst", icon="🤖")
st.caption("Owner: TBD")
st.write(
    "Ask Elina-style questions (\"Where is 5G experience worst?\") and get a "
    "short answer, the table used, and a caveat line (DP noise, suppressed "
    "cells, means not supported for QoE metrics). The LLM tool-calling loop "
    "is a stretch goal (M6.3) and is not built yet."
)

st.text_input(
    "Ask a question about the aggregate release",
    disabled=True,
    placeholder="e.g. Where is 5G experience worst?",
)

st.subheader("Plumbing check: one hard-coded example query")
st.caption("filters={'radio_access_type': '5G'}, group_by=['province'], metrics=['tp_dl_avg_median']")
if st.button("Run example query"):
    try:
        table = agent.query_aggregate(
            filters={"radio_access_type": "5G"},
            group_by=["province"],
            metrics=["tp_dl_avg_median"],
        )
        st.dataframe(table)
    except agent.RefusedQuery as exc:
        st.error(f"Query refused: {exc}")
