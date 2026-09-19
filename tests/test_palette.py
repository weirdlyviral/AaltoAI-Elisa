"""The colour rules for the story and the app, made checkable.

One source of truth (app/static/tokens.css), WCAG AA on the two grounds text and
dots sit on, and pass / fail / residual plus the three network fills staying
distinguishable for normal vision and the three dichromacies.
"""
from __future__ import annotations

import itertools
import math
import re
import tomllib
from pathlib import Path

import pytest

from app.lib import theme

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"

TOKENS = theme.load_tokens()
BG, PANEL = TOKENS["--bg"], TOKENS["--panel"]

# The two colours the Elisa palette cannot supply on a light ground (no purple,
# and its yellows are too pale or too close to red). Everything else in the
# roles layer must resolve to an --eds-color-* primitive.
NON_PALETTE_ROLES = {"--net-5g", "--residual"}
ROLE_TOKENS = [
    "--bg", "--panel", "--panel-2", "--fg", "--fg-dim", "--muted", "--accent", "--on-accent",
    "--net-4g", "--net-5g", "--net-2g", "--ring-safe", "--ring-risk", "--residual", "--ring-dashed",
    "--pass-fill", "--fail-fill", "--residual-fill", "--on-tint",
]
STATUS_AND_NETWORK = ["--ring-safe", "--ring-risk", "--residual", "--net-4g", "--net-5g", "--net-2g"]
TEXT_AND_MARKS = ["--fg", "--fg-dim", "--muted", "--accent", "--ring-dashed", *STATUS_AND_NETWORK]


def _rgb(hex_value: str) -> list[float]:
    h = hex_value.lstrip("#")
    return [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(hex_value: str) -> float:
    r, g, b = (_lin(c) for c in _rgb(hex_value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# Machado, Oliveira & Fernandes (2009), severity 1.0, on linear RGB.
_CVD = {
    "deuteranopia": [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]],
    "protanopia": [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
    "tritanopia": [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.303900]],
}


def _lab(linear_rgb: list[float]) -> tuple[float, float, float]:
    r, g, b = linear_rgb
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116  # noqa: E731
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def _seen_by(hex_value: str, vision: str) -> tuple[float, float, float]:
    linear = [_lin(c) for c in _rgb(hex_value)]
    if vision != "normal":
        m = _CVD[vision]
        linear = [min(1.0, max(0.0, sum(m[i][j] * linear[j] for j in range(3)))) for i in range(3)]
    return _lab(linear)


def worst_case_delta_e(a: str, b: str) -> float:
    return min(
        math.dist(_seen_by(a, vision), _seen_by(b, vision)) for vision in ("normal", *_CVD)
    )


# --------------------------------------------------------------------------- #


def test_every_role_resolves_to_a_hex_and_only_two_leave_the_elisa_palette():
    primitives = {
        value.lower() for name, value in TOKENS.items() if name.startswith("--eds-color-")
    }
    assert len(primitives) >= 40, "the Elisa primitives went missing from tokens.css"
    for role in ROLE_TOKENS:
        assert re.fullmatch(r"#[0-9a-f]{6}", TOKENS[role]), f"{role} is not a hex colour"
        if role not in NON_PALETTE_ROLES:
            assert TOKENS[role] in primitives, f"{role} is {TOKENS[role]}, which is not an Elisa primitive"


@pytest.mark.parametrize("role", TEXT_AND_MARKS)
@pytest.mark.parametrize("ground", ["--bg", "--panel"])
def test_roles_meet_wcag_aa_on_the_bg_and_panel_grounds(role, ground):
    ratio = contrast(TOKENS[role], TOKENS[ground])
    assert ratio >= 4.5, f"{role} on {ground} is {ratio:.2f}:1"


def test_ink_on_coloured_fills_meets_aa():
    # white ink on the strong colours (buttons, current step, trail badges)...
    for fill in ["--accent", "--ring-safe", "--ring-risk", "--residual"]:
        ratio = contrast(TOKENS["--on-accent"], TOKENS[fill])
        assert ratio >= 4.5, f"--on-accent on {fill} is {ratio:.2f}:1"
    # ...and dark ink on the tint fills used for verdict chips.
    for fill in ["--pass-fill", "--fail-fill", "--residual-fill"]:
        ratio = contrast(TOKENS["--on-tint"], TOKENS[fill])
        assert ratio >= 4.5, f"--on-tint on {fill} is {ratio:.2f}:1"


def test_status_and_network_fills_are_pairwise_distinct_for_every_vision_type():
    weakest = sorted(
        (worst_case_delta_e(TOKENS[a], TOKENS[b]), a, b)
        for a, b in itertools.combinations(STATUS_AND_NETWORK, 2)
    )[0]
    # 15 is a deliberate floor, not a comfort figure: the tightest pair (fail
    # red vs residual orange) sits just above it. The first version of this
    # palette had a pair at 0.0 because 5G and the residual chip were one hex.
    assert weakest[0] >= 15, f"{weakest[1]} vs {weakest[2]}: dE {weakest[0]:.1f}"


def test_streamlit_config_repeats_the_token_values():
    theme_cfg = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text())["theme"]
    assert theme_cfg["primaryColor"] == TOKENS["--accent"]
    assert theme_cfg["backgroundColor"] == TOKENS["--bg"]
    assert theme_cfg["secondaryBackgroundColor"] == TOKENS["--panel"]
    assert theme_cfg["textColor"] == TOKENS["--fg"]


def test_no_colour_literal_outside_tokens_css():
    literal = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{8}\b|\brgba?\(|\bhsla?\(")
    offenders = []
    for path in APP_DIR.rglob("*"):
        if not path.is_file() or "vendor" in path.parts or path.name == "tokens.css":
            continue
        if path.suffix not in {".css", ".js", ".html", ".py"}:
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if literal.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert offenders == [], f"colour literals outside tokens.css: {offenders}"
