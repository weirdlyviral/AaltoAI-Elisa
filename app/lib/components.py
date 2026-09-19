"""Reusable UI pieces shared by every page."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from . import theme


def metric_card(label: str, value: str | None, caption: str | None = None) -> None:
    st.metric(label, "—" if value is None else value, help=caption)


def criterion_badge(name: str, status: str) -> None:
    """A traffic-light badge for a pass / fail / residual criterion."""
    color = theme.PALETTE.get(status, theme.PALETTE["neutral"])
    st.markdown(
        f"<span class='aas-badge' style='background:{color}'>"
        f"{name}: {status.upper()}</span>",
        unsafe_allow_html=True,
    )


def before_after(label: str, raw, record, aggregate) -> None:
    cols = st.columns(3)
    cols[0].metric(f"{label} — raw", "—" if raw is None else raw)
    cols[1].metric(f"{label} — record", "—" if record is None else record)
    cols[2].metric(f"{label} — aggregate", "—" if aggregate is None else aggregate)


def step_card(
    number: int,
    title: str,
    body_md: str,
    risk_md: str = "",
    numbers: dict[str, str] | None = None,
) -> None:
    with st.container(border=True):
        st.markdown(f"**Step {number} — {title}**")
        st.markdown(body_md)
        if risk_md:
            st.caption(risk_md)
        if numbers:
            cols = st.columns(len(numbers))
            for col, (label, value) in zip(cols, numbers.items()):
                col.metric(label, value)


def html_block(path_or_str: str, height: int = 300) -> None:
    """Embeds an SVG/HTML diagram, either from a file path or an inline string."""
    path = Path(path_or_str)
    content = path.read_text() if path.exists() else path_or_str
    st.components.v1.html(content, height=height, scrolling=True)


def embedded_story(height: int = 900) -> None:
    """Render the scrollytelling story inside the Streamlit app.

    All assets are bundled into the component so the hosted app needs no
    second static server or public story URL.
    """
    static_dir = Path(__file__).resolve().parents[1] / "static"
    story_dir = static_dir / "story"
    body = (story_dir / "index.html").read_text().split("<body>", 1)[1].split("</body>", 1)[0]
    tokens = (static_dir / "tokens.css").read_text()
    styles = (story_dir / "story.css").read_text().replace(
        '@import url("../vendor/fonts/fonts.css");', ""
    )
    d3 = (static_dir / "vendor" / "d3.v7.min.js").read_text()
    scrollama = (static_dir / "vendor" / "scrollama.min.js").read_text()
    story_js = (story_dir / "story.js").read_text()
    story_data = (story_dir / "story_data.json").read_text()
    content = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>{tokens}\n{styles}</style>
</head>
<body>
{body}
<script>{d3}</script>
<script>{scrollama}</script>
<script>window.__storyData = {story_data};</script>
<script>{story_js}</script>
</body>
</html>"""
    st.components.v1.html(content, height=height, scrolling=True)


def pending(what: str) -> None:
    st.info(f"⏳ Pending: {what} not available yet.")
