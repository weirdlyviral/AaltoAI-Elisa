"""Tests for the M6 app scaffold.

The app must run as a data RECIPIENT: SECURE_DIR unset, no import of
src.safety.load_raw, no reference to SECURE_DIR anywhere under app/.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

APP_DIR = Path(__file__).resolve().parents[1] / "app"

PAGE_FILES = [
    APP_DIR / "Home.py",
    APP_DIR / "pages" / "1_Trade-off_Explorer.py",
    APP_DIR / "pages" / "2_AI_Analyst.py",
    APP_DIR / "pages" / "3_AI_Red_Team.py",
]


@pytest.fixture(autouse=True)
def _secure_dir_unset(monkeypatch):
    monkeypatch.delenv("SECURE_DIR", raising=False)


def test_lib_modules_import_with_secure_dir_unset():
    assert "SECURE_DIR" not in os.environ
    from app.lib import agent, components, data, theme  # noqa: F401


def test_no_app_file_references_load_raw_or_secure_dir():
    offenders = []
    for path in APP_DIR.rglob("*.py"):
        text = path.read_text()
        if "load_raw" in text or "SECURE_DIR" in text:
            offenders.append(str(path))
    assert offenders == [], f"raw-data references found in: {offenders}"


def test_leak_guard_scans_app_directory_clean():
    from src import safety

    assert safety.leak_guard(str(APP_DIR)) is True


def test_data_loader_returns_none_for_missing_file():
    from app.lib import data

    assert data._load_json(Path("/nonexistent/does-not-exist.json")) is None
    assert data.load_release_stats("nonexistent_mode") is None


def test_load_tradeoff_grid_falls_back_to_mock():
    from app.lib import data

    grid, is_mock = data.load_tradeoff_grid()
    assert grid is not None
    assert is_mock is True
    assert all(entry.get("_mock") for entry in grid)


def test_query_aggregate_refuses_small_cell(monkeypatch):
    from app.lib import agent

    tiny = pd.DataFrame(
        {
            "province": ["Uusimaa"],
            "n_subscribers": [5],
            "tp_dl_avg_median": [0.001],
        }
    )
    monkeypatch.setattr(agent.data, "load_aggregate_release", lambda: tiny)

    with pytest.raises(agent.RefusedQuery):
        agent.query_aggregate(filters={}, group_by=["province"], metrics=["tp_dl_avg_median"])


def test_query_aggregate_accepts_cell_above_threshold(monkeypatch):
    from app.lib import agent

    ok = pd.DataFrame(
        {
            "province": ["Uusimaa"],
            "n_subscribers": [50],
            "tp_dl_avg_median": [0.001],
        }
    )
    monkeypatch.setattr(agent.data, "load_aggregate_release", lambda: ok)

    result = agent.query_aggregate(filters={}, group_by=["province"], metrics=["tp_dl_avg_median"])
    assert list(result["n_subscribers"]) == [50]


@pytest.mark.parametrize("page_path", PAGE_FILES, ids=lambda p: p.name)
def test_page_renders_without_exceptions(page_path):
    at = AppTest.from_file(str(page_path))
    at.run()
    assert at.exception == []
