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
# The story is a sticky scrollytelling layout sized in vh. It has to own the
# whole viewport: in a fixed-height iframe taller than the window, its graphic
# pane centres the law cards several hundred pixels below the fold, which is
# what made this page look blank. The parent must not scroll either, so the
# wheel reaches the iframe. (These are Streamlit 1.39 test ids; the previous
# stAppViewBlockContainer rule matched nothing.)
st.markdown(
        """<style>
        html, body,
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"] { overflow: hidden !important; }
        [data-testid="stMainBlockContainer"] {
            max-width: none !important;
            padding: 0 !important;
        }
        [data-testid="stVerticalBlock"] { gap: 0 !important; }
        /* The back link the story's own anchor cannot provide inside the
           sandboxed iframe. Pinned where that anchor used to sit. */
        [data-testid="stPageLink"] {
            position: fixed;
            top: 0.2rem;
            right: 0.9rem;
            width: auto !important;
            z-index: 100;
        }
        [data-testid="stMainBlockContainer"] iframe,
        [data-testid="stIFrame"],
        iframe[title="st.iframe"] {
            height: 100vh !important;
            width: 100% !important;
            border: 0 !important;
        }
        </style>""",
        unsafe_allow_html=True,
)
theme.page_link("Home.py", "← Home")
components.embedded_story(height=900)