"""Tests for the M4 utility evaluation.

All synthetic. The statistics are hand-rolled (scipy is not an allowed
dependency), so they are checked against closed-form cases.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src import anonymise, safety, utility

BUCKET = pd.Timestamp("2027-04-30 16:00:00")


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    secure = tmp_path / "secure"
    (secure / "tmp").mkdir(parents=True)
    monkeypatch.setenv("SECURE_DIR", str(secure))
    saved = set(safety._REGISTRY)
    safety._REGISTRY.clear()
    yield secure
    safety._REGISTRY.clear()
    safety._REGISTRY.update(saved)


def make_joined(n_cells: int = 12, offset: float = 0.0) -> pd.DataFrame:
    """A joined frame of published cells: *_rel from the release, *_raw from raw."""
    rows = []
    for i in range(n_cells):
        raw_median = 100.0 + i * 10
        rows.append(
            {
                "time_bucket": BUCKET,
                "province": f"P{i % 4}",
                "radio_access_type": "5G" if i % 2 else "4G",
                "application_category": f"App{i}",
                "n_subscribers_rel": 50 + i,
                "n_subscribers_raw": 50 + i,
                "n_rows_rel": 500 + i,
                "n_rows_raw": 500 + i,
            }
        )
        for metric in utility.U1_METRICS:
            for statistic in utility.U1_STATISTICS:
                rows[-1][f"{metric}_{statistic}_raw"] = raw_median
                rows[-1][f"{metric}_{statistic}_rel"] = raw_median * (1.0 + offset)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Hand-rolled statistics
# --------------------------------------------------------------------------- #


def test_wasserstein_matches_closed_form_cases():
    assert utility.wasserstein_distance([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 0.0
    # A pure shift of 1 moves every unit of mass by exactly 1.
    assert utility.wasserstein_distance([0.0, 1.0, 2.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)
    assert utility.wasserstein_distance([], [1.0]) is None


def test_ks_statistic_matches_closed_form_cases():
    assert utility.ks_statistic([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 0.0
    # Disjoint supports: the CDFs separate completely.
    assert utility.ks_statistic([0.0, 0.0], [1.0, 1.0]) == pytest.approx(1.0)
    # Half the mass shifted past the other sample.
    assert utility.ks_statistic([0.0, 0.0, 1.0, 1.0], [0.0, 0.0, 0.0, 0.0]) == pytest.approx(0.5)


def test_spearman_matches_closed_form_cases():
    increasing = pd.Series([1.0, 2.0, 3.0, 4.0])
    assert utility.spearman(increasing, increasing) == pytest.approx(1.0)
    assert utility.spearman(increasing, increasing[::-1].reset_index(drop=True)) == pytest.approx(-1.0)
    # Monotone but non-linear: Spearman is 1 where Pearson would not be.
    assert utility.spearman(increasing, pd.Series([1.0, 4.0, 9.0, 16.0])) == pytest.approx(1.0)
    assert utility.spearman(pd.Series([1.0]), pd.Series([1.0])) is None


def test_jaccard_and_relative_error_edge_cases():
    assert utility.jaccard({1, 2}, {1, 2}) == 1.0
    assert utility.jaccard(set(), set()) is None
    errors = utility.relative_error(np.array([1.0, 2.0]), np.array([1.0, 0.0]))
    assert errors[0] == 0.0
    assert np.isnan(errors[1]), "a zero raw value has no defined relative error"


# --------------------------------------------------------------------------- #
# U1
# --------------------------------------------------------------------------- #


def test_identical_medians_give_zero_error():
    result = utility.u1_accuracy(make_joined(offset=0.0))

    headline = result["per_metric"][utility.HEADLINE_METRIC]["median"]
    assert headline["median"] == 0.0
    assert headline["p90"] == 0.0
    assert headline["pct_within_5pct"] == 100.0
    assert result["headline_pass"] is True


def test_error_beyond_tolerance_fails_the_headline():
    result = utility.u1_accuracy(make_joined(offset=0.20))

    assert result["headline_pct_within_5pct"] == 0.0
    assert result["headline_pass"] is False


def test_headline_target_boundary_is_inclusive():
    joined = make_joined(n_cells=10, offset=0.0)
    # Push exactly one cell out of tolerance -> 90%, which must still pass.
    column = f"{utility.HEADLINE_METRIC}_median_rel"
    joined.loc[0, column] = joined.loc[0, f"{utility.HEADLINE_METRIC}_median_raw"] * 1.5

    result = utility.u1_accuracy(joined)

    assert result["headline_pct_within_5pct"] == 90.0
    assert result["headline_pass"] is True


# --------------------------------------------------------------------------- #
# U2
# --------------------------------------------------------------------------- #


def test_coverage_counts_distinct_subscribers_not_rows():
    """One chatty subscriber in a published cell must not inflate coverage."""
    raw_frame = pd.DataFrame(
        [
            # One subscriber, many rows, in the published cell.
            *[
                {
                    "time_bucket": BUCKET,
                    "province": "P0",
                    "radio_access_type": "5G",
                    "application_category": "App0",
                    anonymise.SUBSCRIBER: "s1",
                }
                for _ in range(9)
            ],
            # Three subscribers, one row each, in a cell that was suppressed.
            *[
                {
                    "time_bucket": BUCKET,
                    "province": "P1",
                    "radio_access_type": "5G",
                    "application_category": "App1",
                    anonymise.SUBSCRIBER: f"s{i}",
                }
                for i in range(2, 5)
            ],
        ]
    )
    release = pd.DataFrame(
        [
            {
                "time_bucket": BUCKET,
                "province": "P0",
                "radio_access_type": "5G",
                "application_category": "App0",
            }
        ]
    )

    coverage = utility.u2_coverage(raw_frame, release)

    # 9 of 12 rows, but only 1 of 4 subscribers.
    assert coverage["pct_rows_covered"] == pytest.approx(75.0)
    assert coverage["pct_subscribers_covered"] == pytest.approx(25.0)
    assert coverage["pct_rows_covered"] != coverage["pct_subscribers_covered"]


def test_coverage_splits_by_province_and_technology():
    raw_frame = pd.DataFrame(
        [
            {
                "time_bucket": BUCKET,
                "province": "Covered",
                "radio_access_type": "5G",
                "application_category": "App0",
                anonymise.SUBSCRIBER: "s1",
            },
            {
                "time_bucket": BUCKET,
                "province": "Dropped",
                "radio_access_type": "3G",
                "application_category": "App1",
                anonymise.SUBSCRIBER: "s2",
            },
        ]
    )
    release = pd.DataFrame(
        [
            {
                "time_bucket": BUCKET,
                "province": "Covered",
                "radio_access_type": "5G",
                "application_category": "App0",
            }
        ]
    )

    coverage = utility.u2_coverage(raw_frame, release)

    assert coverage["by_province"]["Covered"]["pct_rows_covered"] == 100.0
    assert coverage["by_province"]["Dropped"]["pct_rows_covered"] == 0.0
    assert coverage["by_radio_access_type"]["3G"]["pct_subscribers_covered"] == 0.0


# --------------------------------------------------------------------------- #
# U3
# --------------------------------------------------------------------------- #


def test_bottom_overlap_is_total_when_release_equals_raw():
    result = utility.u3_product_question(make_joined(n_cells=20, offset=0.0))

    bottom = result["bottom_cells_all"]
    assert bottom["overlap"] == utility.BOTTOM_N == 10
    assert bottom["jaccard"] == 1.0


def test_province_ranking_is_perfectly_correlated_when_release_equals_raw():
    result = utility.u3_product_question(make_joined(n_cells=20, offset=0.0))

    assert result["province_rank_spearman_tp_dl_avg"]["spearman"] == pytest.approx(1.0)


def test_bottom_overlap_degrades_when_the_ranking_is_reversed():
    joined = make_joined(n_cells=20, offset=0.0)
    column = f"{utility.HEADLINE_METRIC}_median_rel"
    joined[column] = joined[column].to_numpy()[::-1]

    result = utility.u3_product_question(joined)

    assert result["bottom_cells_all"]["overlap"] < utility.BOTTOM_N


# --------------------------------------------------------------------------- #
# U4 / U5
# --------------------------------------------------------------------------- #


def test_u4_curve_shows_smaller_epsilon_costing_more_accuracy():
    joined = make_joined(n_cells=200, offset=0.0)
    dp_stats = {"epsilon": 1.0, "noise_scale": 1.0, "assumed_sensitivity": 1}

    result = utility.u4_count_accuracy(joined, dp_stats, "test")

    by_epsilon = {row["epsilon"]: row["median_rel_error"] for row in result["curve"]}
    assert by_epsilon[0.5] > by_epsilon[2.0]
    assert result["deployed_epsilon"] == 1.0
    assert result["deployed_median_rel_error"] == 0.0, "rel == raw in this fixture"


def test_u4_derives_sensitivity_when_it_is_absent():
    joined = make_joined(n_cells=20)
    result = utility.u4_count_accuracy(joined, {"epsilon": 2.0, "noise_scale": 4.0}, "test")

    assert result["assumed_sensitivity"] == pytest.approx(8.0)


def test_u5_flags_a_top_coded_tail():
    rng = np.random.default_rng(safety.SEED)
    values = rng.exponential(1.0, 5000)
    raw_frame = pd.DataFrame({"data_GB_sum": values, anonymise.SUBSCRIBER: "s"})
    capped = pd.DataFrame({"data_GB_sum": np.minimum(values, np.quantile(values, 0.90))})

    result = utility.u5_distribution_fidelity(raw_frame, capped)

    metric = result["metrics"]["data_GB_sum"]
    assert metric["ks_statistic"] > 0
    assert metric["pct_change_p95"] < 0, "top-coding pulls the upper tail down"
    assert "data_GB_sum" in result["tail_flagged_metrics"]


def test_u5_reports_no_change_for_an_untouched_metric():
    rng = np.random.default_rng(safety.SEED)
    values = rng.exponential(1.0, 2000)
    raw_frame = pd.DataFrame({"data_GB_sum": values, anonymise.SUBSCRIBER: "s"})
    same = pd.DataFrame({"data_GB_sum": values})

    result = utility.u5_distribution_fidelity(raw_frame, same)

    metric = result["metrics"]["data_GB_sum"]
    assert metric["wasserstein"] == 0.0
    assert metric["ks_statistic"] == 0.0
    assert metric["tail_flagged"] is False


# --------------------------------------------------------------------------- #
# Output safety
# --------------------------------------------------------------------------- #


def test_no_raw_cell_level_values_appear_in_any_output():
    """Only error statistics may escape - never a raw cell value."""
    sentinel = 987654.321
    joined = make_joined(n_cells=12, offset=0.0)
    for statistic in utility.U1_STATISTICS:
        joined[f"{utility.HEADLINE_METRIC}_{statistic}_raw"] = sentinel
        joined[f"{utility.HEADLINE_METRIC}_{statistic}_rel"] = sentinel

    report = {
        "U1": utility.u1_accuracy(joined),
        "U2": {"pct_rows_covered": 90.0, "pct_subscribers_covered": 90.0,
               "by_province": {"P0": {"pct_rows_covered": 90.0, "pct_subscribers_covered": 90.0}},
               "by_radio_access_type": {"5G": {"pct_rows_covered": 90.0, "pct_subscribers_covered": 90.0}}},
        "U3": utility.u3_product_question(joined),
        "U4": utility.u4_count_accuracy(joined, {"epsilon": 1.0, "noise_scale": 1.0}, "test"),
        "U5": {"metrics": {}, "tail_flagged_metrics": [], "note": ""},
    }

    serialised = json.dumps(report, default=str)
    assert "987654" not in serialised
    assert "987654" not in utility.render_utility_doc(report)


def test_report_and_doc_contain_no_identifier_values(tmp_path: Path):
    safety._REGISTRY.add("358401234567")
    joined = make_joined()
    report = {
        "U1": utility.u1_accuracy(joined),
        "U2": {"pct_rows_covered": 90.0, "pct_subscribers_covered": 90.0,
               "by_province": {"P0": {"pct_rows_covered": 90.0, "pct_subscribers_covered": 90.0}},
               "by_radio_access_type": {"5G": {"pct_rows_covered": 90.0, "pct_subscribers_covered": 90.0}}},
        "U3": utility.u3_product_question(joined),
        "U4": utility.u4_count_accuracy(joined, {"epsilon": 1.0, "noise_scale": 1.0}, "test"),
        "U5": {"metrics": {}, "tail_flagged_metrics": [], "note": ""},
    }

    json_path = safety.safe_write_json(report, tmp_path / "utility_eval.json")
    doc_path = safety.safe_write_text(utility.render_utility_doc(report), tmp_path / "utility.md")

    assert safety.check_file(json_path) == []
    assert safety.check_file(doc_path) == []


def test_u5_flags_a_collapsed_sparse_column():
    """A quantile cap at zero flattens a sparse column; the mean must catch it.

    p95 cannot see this: on a column that is >99% zeros, p95 is already zero in
    both frames, so only the mean (or p99) moves.
    """
    values = np.zeros(10000)
    values[:50] = np.linspace(1.0, 50.0, 50)  # 0.5% non-zero
    raw_frame = pd.DataFrame({"im_video_GB_sum": values, anonymise.SUBSCRIBER: "s"})
    # Top-coding at the 0.99 quantile of a 99.5%-zero column caps everything at 0.
    collapsed = pd.DataFrame({"im_video_GB_sum": np.minimum(values, np.quantile(values, 0.99))})

    result = utility.u5_distribution_fidelity(raw_frame, collapsed)
    metric = result["metrics"]["im_video_GB_sum"]

    assert metric["pct_change_p95"] is None, "p95 is zero in both frames"
    assert metric["pct_change_mean"] == pytest.approx(-100.0)
    assert "mean" in metric["flags"]
    assert metric["severely_degraded"] is True
    assert "im_video_GB_sum" in result["severely_degraded_metrics"]
    assert metric["share_zero_released"] == 1.0
