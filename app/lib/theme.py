"""Page config, shared CSS, header and the persistent recipient-rule footer.

Colours come from one file, app/static/tokens.css, shared with the story page
(app/static/story/story.css): the stylesheet gets it injected, and Python code
(charts, badges) reads the same values through PALETTE below. Fonts are served
by the local static server, which is also what serves the story.
"""
from __future__ import annotations

import re
from pathlib import Path

import streamlit as st

ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
TOKENS_PATH = Path(__file__).resolve().parents[1] / "static" / "tokens.css"

PROJECT_NAME = "Anonymity Assessment Studio"
TAGLINE = "Elisa network data — recipient-side risk & utility, never raw rows"

RECIPIENT_BADGE_TEXT = (
    "This app never accesses raw data — it reads only the published release "
    "and evaluation reports."
)

PROTOTYPE_NOTICE = "Hackathon prototype — not an Elisa product"


def load_tokens(path: Path = TOKENS_PATH) -> dict[str, str]:
    """Resolved value of every custom property declared in tokens.css.

    ``var(--x)`` aliases are followed; ``color-mix`` derivatives stay as written
    (nothing in Python needs them).
    """
    text = re.sub(r"/\*.*?\*/", "", path.read_text(), flags=re.S)
    raw = dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", text))

    def resolve(value: str) -> str:
        value = value.strip()
        alias = re.fullmatch(r"var\((--[\w-]+)\)", value)
        return resolve(raw[alias.group(1)]) if alias else value

    return {name: resolve(value) for name, value in raw.items()}


_TOKENS = load_tokens()

# Semantic roles for Python code. Values are read from tokens.css, not copied.
PALETTE = {
    "pass": _TOKENS["--ring-safe"],
    "fail": _TOKENS["--ring-risk"],
    "residual": _TOKENS["--residual"],
    "neutral": _TOKENS["--muted"],
    "text": _TOKENS["--fg"],
}


def setup_page(title: str, icon: str = "🔒", show_title: bool = True) -> None:
    st.set_page_config(page_title=f"{title} · {PROJECT_NAME}", page_icon=icon, layout="wide")
    _ensure_assets_served()
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


def _ensure_assets_served() -> None:
    """The vendored fonts come from the local static server. Start it from any
    page, not just Home, so deep-linking a tool page doesn't lose the type."""
    try:
        from . import static_server

        static_server.ensure_static_server()
    except OSError:
        pass  # port taken by something else; fonts fall back to the system stack


def _inject_css() -> None:
    # tokens.css first and inline: it must not depend on the static server.
    css = TOKENS_PATH.read_text()
    css_path = ASSETS_DIR / "styles.css"
    if css_path.exists():
        # styles.css names the default static port for its font URLs.
        from . import static_server

        css += css_path.read_text().replace(
            "http://127.0.0.1:8765", f"http://{static_server.HOST}:{static_server.PORT}"
        )
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def _render_footer_badge() -> None:
    st.markdown(
        f"<div class='aas-footer-badge'>🔒 {RECIPIENT_BADGE_TEXT}"
        f"<span class='aas-footer-notice'>{PROTOTYPE_NOTICE}</span></div>",
        unsafe_allow_html=True,
    )
