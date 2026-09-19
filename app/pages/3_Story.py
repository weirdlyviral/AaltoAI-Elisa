"""Hosted walkthrough page with the standalone story bundled in its iframe."""
import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import streamlit as st

from lib import components, theme

theme.setup_page("Anonymisation Walkthrough", icon="▶️", show_sidebar=False)
st.caption("Illustrative dots only — no real records are shown.")
components.embedded_story(height=1200)