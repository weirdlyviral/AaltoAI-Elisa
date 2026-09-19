"""AI Red Team — agentic re-identification strategy, evaluated locally. Owner: TBD.

The agent gets the release schema and an attacker-knowledge TEMPLATE, never
real target values; the harness runs its proposed strategy locally against
sampled targets and returns only the success rate (EDPB paras 83, 92-93).
Stretch goal (M6.3), not built yet. Detail lives in docs/specs/m6.md (6.3).
"""
import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import streamlit as st

from lib import theme

theme.setup_page("AI Red Team", icon="🕵️")
st.caption("Owner: TBD")
st.write(
    "The agent receives the release schema and an attacker-knowledge "
    "TEMPLATE (e.g. \"you know the target's province, radio type, app "
    "category and the 15-minute window\") — never real target values. It "
    "proposes a re-identification strategy as a sequence of tool queries; "
    "the harness runs that strategy locally against 200 sampled targets and "
    "returns only the success rate, alongside a comparison to the M3 "
    "hand-written attacks (EDPB paras 83, 92-93). Stretch goal (M6.3) — not "
    "built yet."
)

st.button("Run attack", disabled=True)
