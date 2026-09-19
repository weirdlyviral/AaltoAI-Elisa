"""Page config, shared CSS, header and the persistent recipient-rule footer."""
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

# Readable in both light and dark themes: dark text/background pairs with
# strong contrast rather than relying on a single hue.
PALETTE = {
    "pass": "#1a7f5a",
    "fail": "#c23b3b",
    "residual": "#b8860b",
    "neutral": "#6b7280",
}


def setup_page(title: str, icon: str = "🔒") -> None:
    st.set_page_config(page_title=f"{title} · {PROJECT_NAME}", page_icon=icon, layout="wide")
    _inject_css()
    st.markdown(
        f"<div class='aas-header'>"
        f"<span class='aas-title'>{PROJECT_NAME}</span>"
        f"<span class='aas-tagline'>{TAGLINE}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )
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
