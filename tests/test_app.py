"""Tests for the M6 app scaffold.

The app must run as a data RECIPIENT: SECURE_DIR unset, no import of
src.safety.load_raw, no reference to SECURE_DIR anywhere under app/.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

APP_DIR = Path(__file__).resolve().parents[1] / "app"
STORY_DIR = APP_DIR / "static" / "story"

PAGE_FILES = [
    APP_DIR / "Home.py",
    APP_DIR / "pages" / "3_Story.py",
    APP_DIR / "pages" / "1_Trade-off_Explorer.py",
    APP_DIR / "pages" / "2_AI_Analyst.py",
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


def test_load_tradeoff_grid_prefers_the_real_grid():
    from app.lib import data

    grid, is_mock = data.load_tradeoff_grid()
    assert grid is not None
    assert is_mock is False, "the precomputed grid exists, so it must be preferred"
    assert not any(entry.get("_mock") for entry in grid)


def test_load_tradeoff_grid_falls_back_to_mock_when_the_real_grid_is_absent(monkeypatch, tmp_path):
    from app.lib import data

    monkeypatch.setattr(data, "OUTPUTS_DIR", tmp_path)
    data.load_tradeoff_grid.clear()
    try:
        grid, is_mock = data.load_tradeoff_grid()
    finally:
        data.load_tradeoff_grid.clear()

    assert is_mock is True
    assert all(entry.get("_mock") for entry in grid)


def test_mock_grid_matches_the_real_grid_schema():
    """The explorer reads metric keys straight off the grid, so a mock with
    different keys would silently render zeros instead of failing loudly."""
    real = json.loads((APP_DIR.parent / "outputs" / "tradeoff_grid.json").read_text())
    mock = json.loads((APP_DIR / "lib" / "mock_tradeoff_grid.json").read_text())

    assert set(mock[0]["metrics"]) == set(real[0]["metrics"])
    assert set(mock[0]["config"]) == set(real[0]["config"])


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
    assert list(result[agent.COUNT_COLUMN]) == [50]
    assert "n_subscribers" not in result.columns


@pytest.fixture
def release(monkeypatch):
    """A two-cell stand-in for the aggregate release, with a datetime bucket."""
    from app.lib import agent

    df = pd.DataFrame(
        {
            "time_bucket": pd.to_datetime(["2027-04-28 12:00", "2027-04-28 12:15"]),
            "province": ["Uusimaa", "Uusimaa"],
            "radio_access_type": ["4G", "5G"],
            "application_category": ["Web", "Web"],
            "n_subscribers": [50, 70],
            "tp_dl_avg_median": [0.25, 0.75],
        }
    )
    monkeypatch.setattr(agent.data, "load_aggregate_release", lambda: df)
    return agent


def test_time_bucket_leaves_the_tool_as_hh_mm(release):
    """Epoch millis are a 13-digit run: safety.check_text flags them and the
    next llm_gateway call is refused, so every time-grouped question died."""
    import re

    from src import safety

    result = release.query_aggregate({}, ["time_bucket"], ["tp_dl_avg_median"])
    payload = result.round(4).to_json(orient="records")

    assert list(result["time_bucket"]) == ["12:00", "12:15"]
    assert not re.search(r"\d{10,}", payload)
    assert safety.check_text(payload, "test_agent_tool_result") == []


def test_time_bucket_filter_accepts_the_string_the_model_sees(release):
    result = release.query_aggregate({"time_bucket": "12:15"}, ["province"], [])
    assert list(result[release.COUNT_COLUMN]) == [70]


def test_unknown_metric_is_refused_not_dropped(release):
    with pytest.raises(release.RefusedQuery, match="unknown metric"):
        release.query_aggregate({}, ["province"], ["latency_median"])


def test_n_subscribers_as_a_metric_does_not_raise_typeerror(release):
    result = release.query_aggregate({}, ["province"], ["n_subscribers"])
    assert list(result[release.COUNT_COLUMN]) == [120]


def test_empty_selection_is_distinguished_from_suppression(release):
    with pytest.raises(release.RefusedQuery, match="no rows matched"):
        release.query_aggregate({"province": "Atlantis"}, ["radio_access_type"], [])


def test_schema_prompt_names_the_real_columns_and_values(release):
    schema = release.describe_schema()
    assert "time_bucket" in schema and "12:00" in schema
    assert "tp_dl_avg_median" in schema
    assert "hour_of_day" not in schema


def _agent_replying(release, monkeypatch, responses):
    """Drive run_agent with canned LLM responses instead of a live gateway."""
    calls = iter(responses)
    monkeypatch.setattr(release, "_llm", lambda prompt, system, purpose: next(calls))
    return release


def test_run_agent_queries_then_answers(release, monkeypatch):
    _agent_replying(
        release,
        monkeypatch,
        [
            '{"action": "query_aggregate", "filters": {}, '
            '"group_by": ["radio_access_type"], "metrics": ["tp_dl_avg_median"]}',
            '{"answer": "5G is faster."}',
        ],
    )
    result = release.run_agent("analyst", "Which is faster?", history=[])

    assert result["answer"].startswith("5G is faster.")
    assert [c["status"] for c in result["tool_calls"]] == ["success"]


def test_run_agent_feeds_a_refusal_back_so_the_model_can_retry(release, monkeypatch):
    _agent_replying(
        release,
        monkeypatch,
        [
            '{"action": "query_aggregate", "filters": {}, "group_by": ["hour"], "metrics": []}',
            '{"action": "query_aggregate", "filters": {}, '
            '"group_by": ["time_bucket"], "metrics": ["tp_dl_avg_median"]}',
            '{"answer": "Throughput rises over the hour."}',
        ],
    )
    result = release.run_agent("analyst", "How does it change over the hour?", history=[])

    assert [c["status"] for c in result["tool_calls"]] == ["error", "success"]
    assert "Valid group_by columns" in result["tool_calls"][0]["error"]
    assert result["answer"].startswith("Throughput rises over the hour.")


def test_run_agent_drops_a_chart_whose_axes_are_not_in_the_result(release, monkeypatch):
    """The old code plotted last_df whatever the model named, so a 'cannot
    plot' answer still rendered a chart built from an unrelated query."""
    _agent_replying(
        release,
        monkeypatch,
        [
            '{"action": "query_aggregate", "filters": {}, '
            '"group_by": ["radio_access_type"], "metrics": ["tp_dl_avg_median"]}',
            '{"answer": "Cannot plot that.", "plot_type": "line", '
            '"x_axis": "hour", "y_axis": "tp_dl_avg_median"}',
        ],
    )
    result = release.run_agent("analyst", "Plot it over time", history=[])
    assert "chart" not in result


def test_run_agent_charts_the_tools_own_numbers(release, monkeypatch):
    _agent_replying(
        release,
        monkeypatch,
        [
            '{"action": "query_aggregate", "filters": {}, '
            '"group_by": ["time_bucket"], "metrics": ["tp_dl_avg_median"]}',
            '{"answer": "Here it is.", "plot_type": "line", '
            '"x_axis": "time_bucket", "y_axis": "tp_dl_avg_median"}',
        ],
    )
    result = release.run_agent("analyst", "Plot throughput over the hour", history=[])

    chart = result["chart"]
    assert chart["mark"] == "line"
    assert [row["time_bucket"] for row in chart["data"]["values"]] == ["12:00", "12:15"]


def test_run_agent_does_not_repeat_the_live_question_from_history(release, monkeypatch):
    seen = {}

    def capture(prompt, system, purpose):
        seen["prompt"] = prompt
        return '{"answer": "ok"}'

    monkeypatch.setattr(release, "_llm", capture)
    history = [{"role": "user", "content": "Which is faster?"}]
    release.run_agent("analyst", "Which is faster?", history=history)

    assert seen["prompt"].count("Which is faster?") == 1


def release_caveat():
    from app.lib import agent

    return agent.CAVEAT


def test_run_agent_appends_the_caveat_when_the_model_forgets_it(release, monkeypatch):
    _agent_replying(release, monkeypatch, ['{"answer": "5G is faster."}'])
    result = release.run_agent("analyst", "Which is faster?", history=[])

    assert result["answer"].startswith("5G is faster.")
    assert result["answer"].endswith(release.CAVEAT)


def test_run_agent_does_not_duplicate_a_caveat_the_model_included(release, monkeypatch):
    _agent_replying(
        release, monkeypatch, ['{"answer": "5G is faster. ' + release_caveat() + '"}']
    )
    result = release.run_agent("analyst", "Which is faster?", history=[])
    assert result["answer"].count("Caveat:") == 1


def test_count_column_requested_as_a_metric_is_ignored(release):
    result = release.query_aggregate({}, ["province"], [release.COUNT_COLUMN])
    assert list(result.columns) == ["province", release.COUNT_COLUMN]


def test_run_agent_reports_a_gateway_failure_instead_of_raising(release, monkeypatch):
    def boom(prompt, system, purpose):
        raise RuntimeError("endpoint unreachable")

    monkeypatch.setattr(release, "_llm", boom)
    result = release.run_agent("analyst", "anything", history=[])

    assert "LLM Gateway Error" in result["answer"]


@pytest.mark.parametrize("page_path", PAGE_FILES, ids=lambda p: p.name)
def test_page_renders_without_exceptions(page_path):
    at = AppTest.from_file(str(page_path))
    at.run()
    assert at.exception == []


def _assert_only_numeric_or_label(value):
    if isinstance(value, dict):
        for key, inner in value.items():
            assert isinstance(key, str)
            _assert_only_numeric_or_label(inner)
    elif isinstance(value, list):
        for inner in value:
            _assert_only_numeric_or_label(inner)
    else:
        assert isinstance(value, (int, float, str)), f"unexpected type in story data: {type(value)}"


def test_export_story_schema_has_no_identifiers_and_passes_leak_guard(tmp_path):
    from app import export_story
    from src import safety

    payload = export_story.build_story_data()

    for key, value in payload.items():
        _assert_only_numeric_or_label(value)

    identifier_like = {"msisdn", "imsi", "imei", "tac"}
    assert not (set(payload.keys()) & identifier_like)

    staged = tmp_path / "story_data.json"
    staged.write_text(json.dumps(payload))
    assert safety.check_file(staged) == []


def test_story_data_json_has_every_key_story_js_uses():
    story_js_text = (STORY_DIR / "story.js").read_text()
    template_keys = set(re.findall(r"\{(\w+)\}", story_js_text))
    direct_keys = set(re.findall(r"\bdata\.(\w+)", story_js_text))
    used_keys = template_keys | direct_keys

    story_data = json.loads((STORY_DIR / "story_data.json").read_text())
    missing = used_keys - set(story_data.keys())
    assert missing == set(), f"story.js references keys missing from story_data.json: {missing}"


def test_leak_guard_scans_story_static_files_clean():
    from src import safety

    assert safety.leak_guard(str(STORY_DIR)) is True


def test_compliance_rows_reference_existing_evidence():
    from app.lib import compliance

    for row in compliance.rows():
        for evidence in row["evidence"]:
            assert (APP_DIR.parent / evidence).exists(), evidence


def test_compliance_measurements_are_in_story_data():
    story_data = json.loads((STORY_DIR / "story_data.json").read_text())
    assert story_data["baseline_unique_pct"] == 99.6
    assert story_data["controls_evidenced"] == 10
    assert story_data["controls_total"] == 10
    assert story_data["criteria_met"] == 3
    assert story_data["criteria_total"] == 3
    assert len(story_data["compliance_rows"]) == 10


def test_red_team_surface_is_removed():
    assert not (APP_DIR / "pages" / ("3_" + "AI_" + "Red_Team.py")).exists()
    text = "\n".join(path.read_text() for path in APP_DIR.rglob("*.py"))
    assert ("AI_" + "Red_Team") not in text
    assert ("red_" + "team") not in text


# --------------------------------------------------------------------------- #
# Verdict rules (app/lib/verdicts.py)
# --------------------------------------------------------------------------- #


def _risk_eval():
    return json.loads((APP_DIR.parent / "outputs" / "risk_eval.json").read_text())


def test_verdict_rules_cover_every_release_criterion_and_approach():
    from app.lib import verdicts

    rows = verdicts.score_all(_risk_eval(), k=10, epsilon=1.0)

    assert [row["criterion"] for row in rows] == list(verdicts.CRITERIA)
    for row in rows:
        for release in verdicts.RELEASES:
            for approach in verdicts.APPROACHES:
                cell = row[f"{release}_{approach}"]
                assert cell["status"] in {verdicts.PASS, verdicts.RESIDUAL, verdicts.FAIL}
                assert cell["why"]


def test_aggregate_no_linkage_passes_because_no_records_exist():
    from app.lib import verdicts

    rows = {row["criterion"]: row for row in verdicts.score_all(_risk_eval())}
    linkage = rows["no_linkage"]

    assert linkage["aggregate_contextual"]["status"] == verdicts.PASS
    assert linkage["aggregate_simplified"]["status"] == verdicts.PASS


def test_a2_trajectory_is_a_counterfactual_not_a_verdict():
    from app.lib import verdicts

    risk = _risk_eval()
    counterfactual = verdicts.counterfactual_linkage(risk)

    assert counterfactual["pct_unique_if_linkable"] > 90
    # ...and it must not appear as a failing linkage verdict anywhere.
    for row in verdicts.score_all(risk):
        if row["criterion"] == "no_linkage":
            statuses = {row[f"{r}_{a}"]["status"] for r in verdicts.RELEASES for a in verdicts.APPROACHES}
            assert statuses == {verdicts.PASS}


def test_identification_probability_above_one_over_k_is_a_fail():
    from app.lib import verdicts

    risk = {
        "attacks": [
            {"id": "A1", "record": {"expected_identification_probability": 0.5}},
            {"id": "A4", "record": {"qi_plus_volume": {"pct_rows_below_k": 0.0}}},
        ]
    }
    rows = {row["criterion"]: row for row in verdicts.score_all(risk, k=10)}

    assert rows["no_record_isolation"]["record_contextual"]["status"] == verdicts.FAIL


def test_tradeoff_grid_passes_the_leak_guard():
    """Unrounded float repr trips the long-digit rule, so the generator has to
    round before writing. This caught a real failure on the first import."""
    from src import safety

    assert safety.check_file(APP_DIR.parent / "outputs" / "tradeoff_grid.json") == []


def test_chart_click_applies_its_config_to_the_controls():
    """A click is handled after the controls are drawn, so it parks the config
    under pending_* and the next run applies it. Writing the widget keys directly
    from the handler silently loses to the widget's own stored value."""
    explorer = APP_DIR / "pages" / "1_Trade-off_Explorer.py"

    at = AppTest.from_file(str(explorer))
    at.run()
    assert at.exception == []
    first_k = at.session_state["slider_k"]

    # AppTest reports a select_slider's options as formatted strings, so take the
    # candidate k from the grid itself, in its real type.
    from app.lib import data

    grid, _ = data.load_tradeoff_grid()
    other_k = next(e["config"]["k"] for e in grid if e["config"]["k"] != first_k)

    at.session_state["pending_slider_k"] = other_k
    at.run()

    assert at.exception == []
    assert at.session_state["slider_k"] == other_k
    assert at.select_slider[0].value == other_k
    assert "pending_slider_k" not in at.session_state
