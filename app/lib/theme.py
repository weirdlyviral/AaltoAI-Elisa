"""Page config, shared CSS, header and the persistent recipient-rule footer.

Palette and typography mirror the story page (app/static/story/story.css) so
the Streamlit app and the story read as one product. Fonts are served by the
local static server, which is also what serves the story.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"

PROJECT_NAME = "Anonymity Assessment Studio"
TAGLINE = "Elisa network data — recipient-side risk & utility, never raw rows"

RECIPIENT_BADGE_TEXT = (
    "This app never accesses raw data — it reads only the published release "
    "and evaluation reports."
)

# Mirrors story.css. Ring colours double as the pass/fail/residual palette.
PALETTE = {
    "pass": "#3ddc97",
    "fail": "#ff6b6b",
    "residual": "#e69f00",
    "neutral": "#7f8ea7",
}


def setup_page(title: str, icon: str = "🔒", show_title: bool = True) -> None:
    st.set_page_config(page_title=f"{title} · {PROJECT_NAME}", page_icon=icon, layout="wide")
    _inject_css()
    st.markdown(
        f"<div class='aas-header'>"
        f"<span class='aas-title'>{PROJECT_NAME}</span>"
        f"<span class='aas-tagline'>{TAGLINE}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )
    if show_title:
        st.title(title)
    _render_footer_badge()


def _inject_css() -> None:
    css_path = ASSETS_DIR / "styles.css"
    if css_path.exists():
        st.markdown(f"<style>{css_path.read_text()}</style>", unsafe_allow_html=True)


def _render_footer_badge() -> None:
    st.markdown(
        f"<div class='aas-footer-badge'>🔒 {RECIPIENT_BADGE_TEXT}</div>",
        unsafe_allow_html=True,
    )
