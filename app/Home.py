"""Home — pipeline visualiser. Owner: Aviral.

Follows the pipeline end to end: what we collected, how we classified it,
what we transformed, what we released, how we attacked it, what we measured,
and what we decided to ship. Detail lives in docs/specs/m6.md (6.1).
"""
import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import streamlit as st

from lib import components, data, theme

theme.setup_page("Home — Pipeline Visualiser", icon="🔒")

st.write(
    "This walkthrough follows the pipeline end to end: what we collected, "
    "how we classified it, what we transformed, what we released, how we "
    "attacked it, what we measured, and what we decided to ship."
)


def _fmt_pct(value: float | None) -> str | None:
    return None if value is None else f"{value:.1f}%"


st.subheader("Headline numbers")
numbers = data.headline_numbers()
cols = st.columns(4)
with cols[0]:
    components.metric_card(
        "Raw: subscribers uniquely singled out",
        _fmt_pct(numbers["baseline_unique_pct"]),
        "QI set D (time_start, enb, radio_access_type, application_category, tac)",
    )
with cols[1]:
    components.metric_card(
        "Raw: identified with 4 (enb, hour) points",
        _fmt_pct(numbers["baseline_4point_pct"]),
        "Among subscribers with ≥4 distinct cell visits in the hour",
    )
with cols[2]:
    components.metric_card(
        "Utility (U1 headline)",
        _fmt_pct(numbers["u1_headline_pct"]),
        "Median tp_dl_avg within 5% of raw, across published cells",
    )
with cols[3]:
    accuracy = numbers["a6_accuracy_pct"]
    bound = numbers["a6_bound_pct"]
    value = None if accuracy is None or bound is None else f"{accuracy:.1f}% / {bound:.1f}%"
    components.metric_card(
        "A6 attacker accuracy vs bound",
        value,
        "Membership inference at the deployed epsilon, vs the theoretical ceiling",
    )

st.subheader("Pipeline diagram")
diagram_path = _APP_DIR / "assets" / "diagrams" / "pipeline.svg"
if diagram_path.exists() and diagram_path.stat().st_size > 0:
    components.html_block(str(diagram_path), height=280)
else:
    components.pending("pipeline diagram (assets/diagrams/pipeline.svg)")

st.subheader("Steps")
STEPS = ["Collect", "Classify", "Transform", "Release", "Attack", "Measure", "Decide"]
for step_number, step_title in enumerate(STEPS, start=1):
    components.step_card(
        step_number,
        step_title,
        "_Detail pending — see docs/specs/m6.md §6.1._",
    )
