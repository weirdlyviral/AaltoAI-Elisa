"""The only module in app/ allowed to touch the filesystem.

Reads exclusively from ``outputs/*.json``, ``outputs/releases/aggregate.parquet``
and ``docs/*.md``. Never imports the pipeline's raw-data reader and never
references the raw-data secure-storage location — the app is a data
RECIPIENT and must run without any access to it configured.

Every loader returns ``None`` (never raises) when its source file is missing,
so pages can render a "pending" placeholder instead of crashing.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUTS_DIR = REPO_ROOT / "outputs"
DOCS_DIR = REPO_ROOT / "docs"
MOCK_TRADEOFF_GRID_PATH = Path(__file__).resolve().parent / "mock_tradeoff_grid.json"

MIN_SUBSCRIBERS_PER_CELL = 10

# --------------------------------------------------------------------------- #
# EDPB Guidelines 02/2026 display-layer mapping.
#
# Pages must always show these labels, even though outputs/risk_eval.json
# (and docs written before M6) still carry the older M3 field names. Renaming
# the JSON itself is M6.0 work on src/ and is out of scope for this scaffold.
# --------------------------------------------------------------------------- #

CRITERION_LABELS: dict[str, str] = {
    "singling_out": "No Record Isolation",
    "linkability": "No Linkage",
    "inference": "No Inference",
}

THREAT_MODEL_LABELS: dict[str, str] = {
    "worst_case": "Simplified approach",
    "realistic": "Contextual approach",
}

# Which EDPB criterion each M3 attack bears on.
ATTACK_CRITERION: dict[str, str] = {
    "A1": "singling_out",
    "A2": "linkability",
    "A3": "inference",
    "A4": "singling_out",
    "A5": "inference",
    "A6": "inference",
}

# The tradeoff grid (real or mock) already stores EDPB-named criteria keys;
# this is display-only prettification, not a rename map.
GRID_CRITERION_LABELS: dict[str, str] = {
    "no_record_isolation": "No Record Isolation",
    "no_linkage": "No Linkage",
    "no_inference": "No Inference",
}


def _load_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    with path.open() as f:
        return json.load(f)


@st.cache_data
def load_profile() -> dict | None:
    return _load_json(OUTPUTS_DIR / "profile.json")


@st.cache_data
def load_baseline_risk() -> dict | None:
    return _load_json(OUTPUTS_DIR / "baseline_risk.json")


@st.cache_data
def load_classification() -> dict | None:
    return _load_json(OUTPUTS_DIR / "classification.json")


@st.cache_data
def load_release_stats(mode: str) -> dict | None:
    return _load_json(OUTPUTS_DIR / f"release_stats_{mode}.json")


@st.cache_data
def load_transform_log(mode: str) -> dict | None:
    return _load_json(OUTPUTS_DIR / f"transform_log_{mode}.json")


@st.cache_data
def load_risk_eval() -> dict | None:
    return _load_json(OUTPUTS_DIR / "risk_eval.json")


@st.cache_data
def load_utility_eval() -> dict | None:
    return _load_json(OUTPUTS_DIR / "utility_eval.json")


@st.cache_data
def load_sweep() -> dict | None:
    return _load_json(OUTPUTS_DIR / "sweep.json")


@st.cache_data
def load_tradeoff_grid() -> tuple[list[dict] | None, bool]:
    """Returns ``(grid, is_mock)``.

    Falls back to the bundled ``app/lib/mock_tradeoff_grid.json`` (fabricated
    numbers, flagged with ``"_mock": true`` on every entry) whenever
    ``outputs/tradeoff_grid.json`` does not exist yet, so the Trade-off
    Explorer page can be built and tested before ``python -m src.tradeoff``
    (M6.2) produces the real file. Pages must show a visible "MOCK DATA"
    banner whenever ``is_mock`` is true.

    Expected schema of outputs/tradeoff_grid.json — a list of:
        {
          "config": {
            "k": int,
            "time_bucket": int,          # minutes
            "area_mode": "enb_tokenised" | "province",
            "epsilon": float | null       # null = no DP noise
          },
          "metrics": { ... },             # % suppressed, coverage, per-attack
                                           # numbers, U1/U3/U4 (free-form, see
                                           # docs/specs/m6.md 6.2 for the list)
          "criteria": {
            "no_record_isolation": "pass" | "fail" | "residual",
            "no_linkage": "pass" | "fail" | "residual",
            "no_inference": "pass" | "fail" | "residual"
          },
          "releasable": bool              # true iff every criterion passes
                                           # under the contextual approach
        }
    """
    real = _load_json(OUTPUTS_DIR / "tradeoff_grid.json")
    if real is not None:
        return real, False
    return _load_json(MOCK_TRADEOFF_GRID_PATH), True


@st.cache_data
def load_aggregate_release() -> pd.DataFrame | None:
    path = OUTPUTS_DIR / "releases" / "aggregate.parquet"
    if not path.exists():
        return None
    return pd.read_parquet(path)


@st.cache_data
def load_decisions() -> list[dict] | None:
    path = OUTPUTS_DIR / "release_decisions.jsonl"
    if not path.exists():
        return None
    records = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


@st.cache_data
def load_doc(name: str) -> str | None:
    """Read a markdown file under docs/ for rendering as text (e.g. the risk
    register, transformations log, or pitch guide)."""
    path = DOCS_DIR / name
    if not path.exists():
        return None
    return path.read_text()


def _pct(value: float | None, decimals: int = 1) -> str | None:
    return None if value is None else f"{value:.{decimals}f}%"


def headline_numbers() -> dict[str, Any]:
    """Key figures for the Home page. Every value is read from the JSON
    reports, never hard-coded; a missing source leaves that figure ``None``."""
    baseline = load_baseline_risk()
    utility = load_utility_eval()
    risk_eval = load_risk_eval()

    numbers: dict[str, Any] = {
        "baseline_unique_pct": None,
        "baseline_4point_pct": None,
        "coverage_subscribers_pct": None,
        "u1_headline_pct": None,
        "a6_accuracy_pct": None,
        "a6_bound_pct": None,
    }

    if baseline:
        numbers["baseline_unique_pct"] = (
            baseline.get("R1", {}).get("D", {}).get("pct_subscribers_with_ge1_unique_row")
        )
        for point_result in (
            baseline.get("R2", {}).get("enb_hour", {}).get("results", [])
        ):
            if point_result.get("p") == 4:
                numbers["baseline_4point_pct"] = point_result.get("pct_uniquely_identified")
                break

    if utility:
        numbers["u1_headline_pct"] = utility.get("U1", {}).get("headline_pct_within_5pct")
        numbers["coverage_subscribers_pct"] = utility.get("U2", {}).get("pct_subscribers_covered")

    if risk_eval:
        for attack in risk_eval.get("attacks", []):
            if attack.get("id") != "A6":
                continue
            for point in attack.get("aggregate", {}).get("worst_case_grid", []):
                if point.get("dp_epsilon") == 1.0:
                    numbers["a6_accuracy_pct"] = point.get("attacker_accuracy_pct")
                    numbers["a6_bound_pct"] = point.get("theoretical_bound_pct")
                    break
            break

    return numbers
