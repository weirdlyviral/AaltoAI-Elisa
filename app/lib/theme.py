"""Page config, shared CSS, header and the persistent recipient-rule footer.

Colours come from one file, app/static/tokens.css, shared with the story page
(app/static/story/story.css): the stylesheet gets it injected, and Python code
(charts, badges) reads the same values through PALETTE below. Fonts are served
by the local static server, which is also what serves the story.
"""
from __future__ import annotations

import base64
import functools
import os
import re
from pathlib import Path

import streamlit as st

ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
TOKENS_PATH = Path(__file__).resolve().parents[1] / "static" / "tokens.css"
FONTS_DIR = Path(__file__).resolve().parents[1] / "static" / "vendor" / "fonts"

PROJECT_NAME = "Anonymity Assessment Studio"
TAGLINE = "Elisa network data — recipient-side risk & utility, never raw rows"

RECIPIENT_BADGE_TEXT = (
    "This app never accesses raw data — it reads only the published release "
    "and evaluation reports."
)

PROTOTYPE_NOTICE = "Hackathon prototype — not an Elisa product"

NAV_PAGES = (
    ("Home.py", "Home"),
    ("pages/1_Trade-off_Explorer.py", "Explorer"),
    ("pages/2_AI_Analyst.py", "AI Analyst"),
)

# setup_page title -> nav label. The Story page is deliberately absent from
# the nav and maps to nothing, so it highlights no entry.
NAV_LABEL_BY_TITLE = {
    PROJECT_NAME: "Home",
    "Trade-off Explorer": "Explorer",
    "AI Analyst": "AI Analyst",
}


def _load_hosted_secrets() -> None:
    """Copy Streamlit Cloud secrets into the environment-based app contract."""
    names = (
        "AAS_STORY_URL",
        "AGGREGATE_RELEASE_URL",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL",
    )
    try:
        secrets = st.secrets
    except Exception:
        return
    try:
        for name in names:
            if not os.getenv(name) and name in secrets:
                os.environ[name] = str(secrets[name])
    except FileNotFoundError:
        # Local development and tests commonly have no secrets.toml.
        return


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


def setup_page(
    title: str,
    icon: str = "🔒",
    show_title: bool = True,
    show_sidebar: bool = False,
    show_nav: bool = True,
    show_header: bool = True,
    show_footer: bool = True,
) -> None:
    st.set_page_config(
        page_title=f"{title} · {PROJECT_NAME}",
        page_icon=icon,
        layout="wide",
        initial_sidebar_state="expanded" if show_sidebar else "collapsed",
    )
    _load_hosted_secrets()
    _ensure_assets_served()
    _inject_css()
    if not show_sidebar:
        # Streamlit 1.39 test ids. 'collapsedControl' is not in this DOM, which
        # is why the expand chevron survived every previous attempt to hide it.
        # stHeader is hidden for all pages from styles.css, not from here.
        st.markdown(
            "<style>[data-testid='stSidebar'],"
            " [data-testid='stSidebarCollapsedControl'],"
            " [data-testid='stSidebarCollapseButton']"
            " { display: none !important; }</style>",
            unsafe_allow_html=True,
        )
    if show_nav:
        _render_nav(NAV_LABEL_BY_TITLE.get(title, ""))
    if show_header:
        st.markdown(
            f"<div class='aas-header'>"
            f"<span class='aas-title'>{PROJECT_NAME}</span>"
            f"<span class='aas-tagline'>{TAGLINE}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        if show_title:
            st.title(title)
    if show_footer:
        _render_footer_badge()


def page_link(path: str, label: str) -> None:
    """st.page_link, with a plain-link fallback.

    AppTest runs a page as its own entrypoint, so sibling pages are unknown to
    it and st.page_link raises; the app itself always takes the first branch.
    """
    try:
        st.page_link(path, label=label)
    except st.errors.StreamlitPageNotFoundError:
        st.markdown(f"[{label}]({path})")


def _render_nav(active: str = "") -> None:
    """The top row. The current page renders as a marker, not as a link."""

    def entry(path: str, label: str) -> None:
        if label and label == active:
            st.markdown(
                # a div, not a span: markdown wraps inline HTML in a <p>
                # with margins of its own, which lifted the label off the
                # baseline the links sit on.
                f"<div class='aas-nav-current'>"
                f"<span class='aas-nav-label'>{label}</span></div>",
                unsafe_allow_html=True,
            )
            return
        page_link(path, label)

    nav = st.columns([2, 1.25, 1.25, 1.25, 2], gap="small")
    for column, (path, label) in zip(nav[1:4], NAV_PAGES):
        with column:
            entry(path, label)


def _ensure_assets_served() -> None:
    """The vendored fonts come from the local static server. Start it from any
    page, not just Home, so deep-linking a tool page doesn't lose the type."""
    try:
        from . import static_server

        static_server.ensure_static_server()
    except OSError:
        pass  # port taken by something else; fonts fall back to the system stack


@functools.lru_cache(maxsize=1)
def font_face_css() -> str:
    """The two @font-face rules with their woff2 inlined as data URIs.

    A hosted deployment has no origin of its own to serve a binary from
    (lib/static_server.py explains why Streamlit's static route is unusable),
    and the story runs inside a srcdoc iframe, which has no base URL a relative
    src could resolve against. A data URI is the only src that works on both
    surfaces. ~99 KB of woff2, ~133 KB once base64-encoded.
    """
    faces = (
        ("Inter", "100 900", "inter-latin-var.woff2"),
        ("Source Serif 4", "200 900", "source-serif-4-latin-var.woff2"),
    )
    rules = []
    for family, weight, filename in faces:
        encoded = base64.b64encode((FONTS_DIR / filename).read_bytes()).decode("ascii")
        rules.append(
            "@font-face {\n"
            f'  font-family: "{family}";\n'
            "  font-style: normal;\n"
            f"  font-weight: {weight};\n"
            "  font-display: swap;\n"
            f'  src: url("data:font/woff2;base64,{encoded}") format("woff2");\n'
            "}\n"
        )
    return "\n".join(rules)


def _inject_css() -> None:
    # Fonts first, then tokens.css: neither may depend on the static server.
    css = font_face_css() + TOKENS_PATH.read_text()
    css_path = ASSETS_DIR / "styles.css"
    if css_path.exists():
        css += css_path.read_text()
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def _render_footer_badge() -> None:
    st.markdown(
        f"<div class='aas-footer-badge'>🔒 {RECIPIENT_BADGE_TEXT}"
        f"<span class='aas-footer-notice'>{PROTOTYPE_NOTICE}</span></div>",
        unsafe_allow_html=True,
    )
