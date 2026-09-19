"""Hosted walkthrough page with the standalone story bundled in its iframe."""
import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import streamlit as st

from lib import components, theme

theme.setup_page(
        "Anonymisation Walkthrough",
        icon="▶️",
        show_sidebar=False,
        show_nav=False,
        show_header=False,
        show_footer=False,
)
st.markdown(
        """<style>
        [data-testid="stAppViewContainer"] > .main { padding-top: 0 !important; }
        [data-testid="stAppViewBlockContainer"] {
            max-width: none !important;
            padding: 0 !important;
        }
        [data-testid="stDecoration"] { display: none !important; }
        </style>""",
        unsafe_allow_html=True,
)
components.embedded_story(height=1500)