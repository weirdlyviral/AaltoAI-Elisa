"""Home — hero + entry point into the scrollytelling story. Owner: Aviral.

The step-by-step pipeline walkthrough lives in the standalone story page
(app/static/story/), built per docs/specs/m6_home_story_v2.md. This page is
the landing hub: one hero line, three before/after statements, a big link
into the story, and the three tool pages.
"""
import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import streamlit as st

from lib import data, theme

theme.setup_page("Anonymity Assessment Studio", icon="🔒", show_title=False)

st.markdown(
    "<div class='aas-eyebrow'>Elisa challenge · EDPB Guidelines 02/2026</div>",
    unsafe_allow_html=True,
)
st.markdown(
    "<div class='aas-hero'>How do you share network data without sharing people?</div>",
    unsafe_allow_html=True,
)
st.markdown(
    "<div class='aas-sub'>One hour of Elisa's mobile network, transformed so a product "
    "team can use it — with the remaining re-identification risk measured rather than "
    "asserted.</div>",
    unsafe_allow_html=True,
)


def _pct(value: float | None, decimals: int = 1) -> str:
    return "—" if value is None else f"{value:.{decimals}f}%"


def _stat_card(value_html: str, head: str, note: str) -> str:
    return (
        f"<div class='aas-stat'><div class='aas-stat-value'>{value_html}</div>"
        f"<div class='aas-stat-head'>{head}</div>"
        f"<div class='aas-stat-note'>{note}</div></div>"
    )


numbers = data.headline_numbers()
unique_rows = numbers["a1_unique_rows_pct"]
after_value = "0" if unique_rows == 0 else _pct(unique_rows, 2)

cols = st.columns(3, gap="medium")
with cols[0]:
    st.markdown(
        _stat_card(
            f"{_pct(numbers['baseline_unique_pct'])} → <span class='aas-after'>{after_value}</span>",
            "subscribers with a unique row, before → after",
            "Share of subscribers owning at least one row unique on the quasi-identifiers, "
            "raw versus the published record release.",
        ),
        unsafe_allow_html=True,
    )
with cols[1]:
    st.markdown(
        _stat_card(
            _pct(numbers["u1_headline_pct"]),
            "of published cells keep download speed within 5%",
            "Median download throughput per published cell, compared against the same cell "
            "computed on raw data.",
        ),
        unsafe_allow_html=True,
    )
with cols[2]:
    st.markdown(
        _stat_card(
            _pct(numbers["a6_accuracy_pct"]),
            "membership guess, against a 50% coin flip",
            "An attacker with every other subscriber's data trying to tell whether one person "
            "is in the release, at the deployed privacy budget.",
        ),
        unsafe_allow_html=True,
    )

st.write("")

st.markdown("<div class='aas-section-label'>Walkthrough</div>", unsafe_allow_html=True)
st.markdown(
    "<a class='aas-cta' href='Story' target='_self'>"
    "<span class='aas-cta-label'>▶ Open the anonymisation walkthrough</span>"
    "<span class='aas-cta-note'>15 beats · illustrative dots only, no real records</span>"
    "</a>",
    unsafe_allow_html=True,
)

st.markdown("<div class='aas-section-label'>Tools</div>", unsafe_allow_html=True)

TOOLS = [
    (
        "Trade-off Explorer",
        "Trade-off_Explorer",
        "Move k, the time bucket and the privacy budget, and watch risk and utility trade off "
        "against each other before approving a release.",
    ),
    (
        "AI Analyst",
        "AI_Analyst",
        "Ask questions of the published aggregates in plain language; the assistant may only "
        "query cells covering ten or more subscribers.",
    ),
]

tool_cols = st.columns(len(TOOLS), gap="medium")
for col, (name, slug, description) in zip(tool_cols, TOOLS):
    with col:
        # Spans, not divs: a block element inside an inline <a> makes the HTML
        # parser close and re-open the anchor, splitting one card into three.
        st.markdown(
            f"<a class='aas-tool' href='{slug}' target='_self'>"
            f"<span class='aas-tool-name'>{name}</span>"
            f"<span class='aas-tool-desc'>{description}</span></a>",
            unsafe_allow_html=True,
        )
