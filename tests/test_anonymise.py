"""Tests for the M2 anonymisation step.

Every test builds its own synthetic frame. No raw data is touched, and the
fabricated identifiers below never appear in any assertion output.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from src import anonymise, safety

PROVINCES = ("Uusimaa", "Pirkanmaa")


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


def base_config(**overrides) -> dict:
    config = {
        "k": 3,
        "time_bucket_minutes": 15,
        "area_mode": "enb_tokenised",
        "min_subscribers_per_area": 3,
        "rare_category_min_subscribers": 3,
        "numeric_winsorise": [0.01, 0.99],
        "numeric_round_sig_figs": 3,
        "volume_top_code_quantile": 0.99,
        "aggregate_min_subscribers_per_cell": 3,
        "dp_epsilon": None,
    }
    config.update(overrides)
    return config


def make_df(
    n_subscribers: int = 12,
    rows_per_subscriber: int = 4,
    busy_enb: str = "100000000001",
    rare_enb: str = "100000000099",
) -> pd.DataFrame:
    """A small frame: most subscribers share one cell, one cell is rare."""
    rows = []
    start = pd.Timestamp("2027-04-30 16:00:00")
    for s in range(n_subscribers):
        msisdn = f"3584010000{s:02d}"
        for r in range(rows_per_subscriber):
            rows.append(
                {
                    "time_start": start + pd.Timedelta(minutes=10 * r),
                    "msisdn": msisdn,
                    "imsi": f"24412000000{s:04d}",
                    "imei": f"35693800000{s:04d}",
                    "enb": busy_enb,
                    "province": PROVINCES[s % len(PROVINCES)],
                    "radio_access_type": "5G",
                    "application_category": "Streaming",
                    "tp_dl_avg": 1000.0 + s * 10 + r,
                    "cont_rtt_radio_avg": 20.0 + s,
                    "http_response_time_avg": 100.0 + s,
                    "data_GB_sum": 0.5 + s * 0.1,
                    "im_video_GB_sum": 0.1,
                    "im_audio_GB_sum": 0.05,
                    "tethering_data_GB_dl_sum": 0.0,
                }
            )
    # One subscriber alone in a rare cell with a rare app category.
    rows.append(
        {
            "time_start": start,
            "msisdn": "358401009999",
            "imsi": "244120000009999",
            "imei": "356938000009999",
            "enb": rare_enb,
            "province": "Lappi",
            "radio_access_type": "3G",
            "application_category": "Gaming",
            "tp_dl_avg": 50.0,
            "cont_rtt_radio_avg": 400.0,
            "http_response_time_avg": 900.0,
            "data_GB_sum": 99.0,
            "im_video_GB_sum": 9.0,
            "im_audio_GB_sum": 9.0,
            "tethering_data_GB_dl_sum": 5.0,
        }
    )
    df = pd.DataFrame(rows)
    for column in ("msisdn", "imsi", "imei"):
        df[column] = df[column].astype("string")
    safety.register_identifiers(df)
    return safety.add_tac(df)


def prepared_frame(config: dict | None = None):
    config = config or base_config()
    log = anonymise.TransformLog()
    prepared, meta = anonymise.prepare(make_df(), config, log)
    return prepared, log, config, meta


# --------------------------------------------------------------------------- #
# Identifiers
# --------------------------------------------------------------------------- #


def test_session_is_optional_and_excluded_from_the_default_set():
    assert "session" in anonymise.OPTIONAL_MODES
    assert "session" not in anonymise.DEFAULT_MODES
    assert anonymise.DEFAULT_MODES[0] == "aggregate", "aggregate is the headline release"


def test_identifier_columns_are_removed():
    prepared, log, config, _ = prepared_frame()
    release, _ = anonymise.build_release(prepared, "record", config, log)

    for column in anonymise.IDENTIFIER_COLUMNS:
        assert column not in release.columns
    assert anonymise.SUBSCRIBER not in release.columns
    assert "time_start" not in release.columns
    assert "enb" not in release.columns


def test_release_passes_the_leak_guard(tmp_path: Path):
    prepared, log, config, _ = prepared_frame()
    release, _ = anonymise.build_release(prepared, "record", config, log)

    target = safety.safe_write_df(release, tmp_path / "record.parquet")

    assert target.exists()
    assert safety.check_file(target) == []


# --------------------------------------------------------------------------- #
# k-anonymity on DISTINCT SUBSCRIBERS
# --------------------------------------------------------------------------- #


def test_k_counts_distinct_subscribers_not_rows():
    """One subscriber with many rows must never satisfy k on their own."""
    config = base_config(k=3, min_subscribers_per_area=1, rare_category_min_subscribers=1)
    log = anonymise.TransformLog()
    # A single subscriber contributing 10 rows in their own cell and province.
    rows = [
        {
            "time_start": pd.Timestamp("2027-04-30 16:00:00"),
            "msisdn": "358401007777",
            "imsi": "244120000007777",
            "imei": "356938000007777",
            "enb": "100000000777",
            "province": "Kainuu",
            "radio_access_type": "5G",
            "application_category": "Streaming",
            "tp_dl_avg": 100.0 + i,
            "cont_rtt_radio_avg": 20.0,
            "http_response_time_avg": 50.0,
            "data_GB_sum": 1.0,
            "im_video_GB_sum": 0.0,
            "im_audio_GB_sum": 0.0,
            "tethering_data_GB_dl_sum": 0.0,
        }
        for i in range(10)
    ]
    df = pd.DataFrame(rows)
    for column in ("msisdn", "imsi", "imei"):
        df[column] = df[column].astype("string")
    safety.register_identifiers(df)
    prepared, _ = anonymise.prepare(safety.add_tac(df), config, log)

    out, stats = anonymise.enforce_k_anonymity(prepared, k=3)

    assert len(out) == 0, "10 rows from 1 subscriber must not satisfy k=3"
    assert stats["rows_suppressed"] == 10


def test_k_is_satisfied_in_the_written_release():
    prepared, log, config, _ = prepared_frame()
    out, stats = anonymise.enforce_k_anonymity(prepared, k=config["k"])

    assert stats["min_subscribers_per_group"] >= config["k"]
    assert stats["rows_out"] == len(out)


# --------------------------------------------------------------------------- #
# Area handling
# --------------------------------------------------------------------------- #


def test_rare_enb_becomes_province_other():
    prepared, _, _, _ = prepared_frame()

    areas = set(prepared["area"].unique())

    assert "Lappi_OTHER" in areas


def test_area_tokens_never_equal_raw_enb_values():
    raw = make_df()
    raw_enbs = set(raw["enb"].astype(str).unique())
    prepared, _, _, _ = prepared_frame()

    areas = set(prepared["area"].dropna().astype(str).unique())

    assert not (areas & raw_enbs)
    assert any(a.startswith("A") for a in areas)


def test_province_area_mode_uses_province_directly():
    config = base_config(area_mode="province")
    prepared, _, _, _ = prepared_frame(config)

    assert set(prepared["area"].unique()) <= set(prepared["province"].unique())


def test_assert_release_safe_rejects_raw_enb_in_area():
    raw = make_df()
    raw_enbs = set(raw["enb"].astype(str).unique())
    leaky = pd.DataFrame(
        {
            "time_bucket": [pd.Timestamp("2027-04-30 16:00:00")],
            "area": [next(iter(raw_enbs))],
            "radio_access_type": ["5G"],
            "application_category": ["Streaming"],
        }
    )

    with pytest.raises(safety.LeakError, match="raw enb"):
        anonymise.assert_release_safe(leaky, "record", 3, raw_enbs, tokenised=True)


def test_assert_release_safe_rejects_identifier_column():
    df = pd.DataFrame({"msisdn": ["358401000000"], "area": ["A0001"]})

    with pytest.raises(safety.LeakError, match="identifier column"):
        anonymise.assert_release_safe(df, "record", 3, set(), tokenised=False)


# --------------------------------------------------------------------------- #
# Session mode
# --------------------------------------------------------------------------- #


def test_session_key_appears_in_no_output_or_log(tmp_path: Path):
    prepared, log, config, _ = prepared_frame()
    release, _ = anonymise.build_release(prepared, "session", config, log)

    assert "session_id" in release.columns
    assert anonymise.SUBSCRIBER not in release.columns

    # The session id must link a subscriber's rows but not be a raw identifier.
    assert release["session_id"].nunique() > 1
    serialised = json.dumps(log.as_list())
    assert "key" not in serialised.lower() or "ephemeral key" in serialised
    for token in release["session_id"].unique():
        assert not str(token).isdigit(), "an all-digit id would trip the leak guard"

    target = safety.safe_write_df(release, tmp_path / "session.parquet")
    assert safety.check_file(target) == []


def test_session_ids_are_stable_within_a_release():
    prepared, log, config, _ = prepared_frame()
    release, _ = anonymise.build_release(prepared, "session", config, log)

    counts = release.groupby("session_id").size()
    assert counts.max() > 1, "session_id should link a subscriber's rows"


def test_session_ids_differ_between_runs():
    """The HMAC key is ephemeral, so ids must not be reproducible."""
    prepared, log_a, config, _ = prepared_frame()
    first, _ = anonymise.build_release(prepared, "session", config, log_a)
    prepared_b, log_b, config_b, _ = prepared_frame()
    second, _ = anonymise.build_release(prepared_b, "session", config_b, log_b)

    assert set(first["session_id"]) != set(second["session_id"])


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #


def test_suppression_and_escalation_counts_are_logged():
    prepared, log, config, _ = prepared_frame()
    _, stats = anonymise.build_release(prepared, "record", config, log)

    actions = {entry.action for entry in log.entries}
    assert any("escalated to province" in a for a in actions)
    assert any("suppressed" in a for a in actions)
    assert "rows_suppressed" in stats
    assert "rows_escalated_to_province" in stats
    assert stats["pct_suppressed"] is not None


def test_transform_log_entries_carry_params_and_counts():
    _, log, _, _ = prepared_frame()

    assert log.entries
    for entry in log.as_list():
        assert set(entry) >= {"field", "action", "params", "rows_affected"}
        assert isinstance(entry["rows_affected"], int)


# --------------------------------------------------------------------------- #
# Numeric treatment
# --------------------------------------------------------------------------- #


def test_round_sig_figs_preserves_zero_and_nan():
    series = pd.Series([0.0, float("nan"), 123456.0, 0.000123456])

    out = anonymise.round_sig_figs(series, 3)

    assert out.iloc[0] == 0.0
    assert pd.isna(out.iloc[1])
    assert out.iloc[2] == 123000.0
    assert out.iloc[3] == pytest.approx(0.000123)


def test_native_window_wins_when_coarser():
    df = make_df()
    effective, native = anonymise.effective_bucket_minutes(df, configured=5)

    assert native == 10
    assert effective == 10, "a 5-minute bucket must not be finer than the native window"


def test_volumes_are_top_coded():
    prepared, _, _, _ = prepared_frame()

    # The outlier subscriber had 99 GB; top-coding at p99 must pull it down.
    assert prepared["data_GB_sum"].max() < 99.0


# --------------------------------------------------------------------------- #
# Aggregate mode
# --------------------------------------------------------------------------- #


def test_aggregate_suppresses_thin_cells():
    prepared, log, config, _ = prepared_frame()
    out, stats = anonymise.build_release(prepared, "aggregate", config, log)

    assert (out["n_subscribers"] >= config["aggregate_min_subscribers_per_cell"]).all()
    assert stats["cells_suppressed"] >= 1
    assert anonymise.SUBSCRIBER not in out.columns


def test_aggregate_dp_records_epsilon_and_scale():
    prepared, log, _, _ = prepared_frame()
    config = base_config(dp_epsilon=0.5)
    _, stats = anonymise.build_release(prepared, "aggregate", config, log)

    dp = stats["dp"]
    assert dp["applied"] is True
    assert dp["epsilon"] == 0.5
    assert dp["noise_scale"] == 2.0
    assert dp["mechanism"] == "Laplace"
    assert dp["seed"] == safety.SEED
    assert set(dp["noised_columns"]) == {"n_subscribers", "n_rows"}
    assert dp["caveats"], "the sensitivity caveat must be recorded, not implied"


def test_aggregate_without_epsilon_records_no_noise():
    prepared, log, _, _ = prepared_frame()
    config = base_config(dp_epsilon=None)
    _, stats = anonymise.build_release(prepared, "aggregate", config, log)

    assert stats["dp"]["applied"] is False
    assert stats["dp"]["epsilon"] is None


def test_dp_noise_actually_perturbs_counts():
    prepared, log, _, _ = prepared_frame()
    cells, _ = anonymise.aggregate_cells(prepared, base_config(), log)
    noisy, _ = anonymise.apply_dp_noise(cells, 0.5)

    assert not cells["n_subscribers"].equals(noisy["n_subscribers"])
    assert (noisy["n_subscribers"] >= 0).all(), "counts must stay non-negative"


def test_dp_noise_is_deterministic_under_the_seed():
    prepared, log, _, _ = prepared_frame()
    cells, _ = anonymise.aggregate_cells(prepared, base_config(), log)

    first, _ = anonymise.apply_dp_noise(cells, 1.0)
    second, _ = anonymise.apply_dp_noise(cells, 1.0)

    assert first["n_subscribers"].equals(second["n_subscribers"])


def test_smaller_epsilon_means_more_noise():
    prepared, log, _, _ = prepared_frame()
    cells, _ = anonymise.aggregate_cells(prepared, base_config(), log)

    loose, _ = anonymise.apply_dp_noise(cells, 2.0)
    tight, _ = anonymise.apply_dp_noise(cells, 0.25)

    loose_err = anonymise.count_relative_error(cells, loose)["median_rel_error_n_subscribers"]
    tight_err = anonymise.count_relative_error(cells, tight)["median_rel_error_n_subscribers"]
    assert tight_err > loose_err


# --------------------------------------------------------------------------- #
# Differencing defence
# --------------------------------------------------------------------------- #


def test_secondary_suppression_hits_an_affected_slice():
    """A slice that loses a cell must lose its smallest survivor too."""
    log = anonymise.TransformLog()
    # Two cells in one (bucket, province) slice: one thin, one large.
    frame = pd.DataFrame(
        {
            "time_bucket": [pd.Timestamp("2027-04-30 16:00:00")] * 3,
            "province": ["Uusimaa"] * 3,
            "radio_access_type": ["5G", "5G", "5G"],
            "application_category": ["Thin", "Medium", "Large"],
            anonymise.SUBSCRIBER: ["a", "b", "c"],
            "data_GB_sum": [1.0, 1.0, 1.0],
        }
    )
    # Inflate Medium and Large past the threshold; leave Thin below it.
    frame = pd.concat(
        [frame]
        + [
            frame[frame["application_category"] == "Medium"].assign(
                **{anonymise.SUBSCRIBER: f"m{i}"}
            )
            for i in range(4)
        ]
        + [
            frame[frame["application_category"] == "Large"].assign(
                **{anonymise.SUBSCRIBER: f"l{i}"}
            )
            for i in range(9)
        ],
        ignore_index=True,
    )

    out, stats = anonymise.aggregate_cells(frame, base_config(aggregate_min_subscribers_per_cell=4), log)

    assert stats["cells_suppressed_primary"] >= 1
    assert stats["cells_suppressed_secondary"] >= 1
    surviving = set(out["application_category"])
    assert "Thin" not in surviving, "the thin cell is primary-suppressed"
    assert "Medium" not in surviving, "the smallest survivor is secondary-suppressed"
    assert "Large" in surviving


def test_no_secondary_suppression_when_nothing_was_primary_suppressed():
    log = anonymise.TransformLog()
    prepared, _ = anonymise.prepare(make_df(), base_config(), log)
    config = base_config(aggregate_min_subscribers_per_cell=1)

    _, stats = anonymise.aggregate_cells(prepared, config, log)

    assert stats["cells_suppressed_primary"] == 0
    assert stats["cells_suppressed_secondary"] == 0


def test_aggregate_publishes_one_granularity_only():
    prepared, log, config, _ = prepared_frame()
    out, stats = anonymise.build_release(prepared, "aggregate", config, log)

    assert stats["single_granularity_only"] is True
    assert stats["granularity"] == [c for c in anonymise.AGGREGATE_KEYS if c in out.columns]


# --------------------------------------------------------------------------- #
# Sweep
# --------------------------------------------------------------------------- #


def test_record_sweep_covers_the_grid():
    sweep = anonymise.run_sweep(make_df(), base_config())

    expected = len(anonymise.SWEEP_BUCKETS) * len(anonymise.SWEEP_AREA_MODES) * len(anonymise.SWEEP_K)
    assert len(sweep["record"]["results"]) == expected
    for row in sweep["record"]["results"]:
        assert set(row) >= {
            "time_bucket",
            "area_mode",
            "k",
            "pct_rows_suppressed",
            "pct_rows_escalated",
            "n_qi_groups",
            "median_subscribers_per_group",
        }


def test_aggregate_sweep_covers_every_epsilon():
    sweep = anonymise.run_sweep(make_df(), base_config())
    results = sweep["aggregate"]["results"]

    assert len(results) == len(anonymise.SWEEP_EPSILONS)
    assert [r["dp_epsilon"] for r in results] == [0.5, 1.0, 2.0, "none"]
    for row in results:
        assert set(row) >= {
            "dp_epsilon",
            "pct_cells_suppressed",
            "median_rel_error_n_subscribers",
            "median_rel_error_n_rows",
            "mean_rel_error_n_subscribers",
        }
    # Suppression is decided on true counts, so it cannot vary with epsilon.
    assert len({r["pct_cells_suppressed"] for r in results}) == 1
    # Exact counts carry no error.
    assert results[-1]["median_rel_error_n_subscribers"] == 0.0


# --------------------------------------------------------------------------- #
# Column coverage
# --------------------------------------------------------------------------- #

DATASET_NUMERIC_COLUMNS = (
    "tp_dl_avg",
    "tp_ul_avg",
    "tp_dl_filtered_avg",
    "cont_rtt_radio_avg",
    "cont_rtt_internet_avg",
    "initial_rtt_radio_avg",
    "tcp_retrans_byte_ratio_downlink_avg",
    "tcp_retrans_byte_ratio_uplink_avg",
    "http_response_time_avg",
    "http_sr_avg",
    "data_GB_sum",
    "im_video_GB_sum",
    "im_audio_GB_sum",
    "tethering_data_GB_dl_sum",
)


def test_every_numeric_column_is_covered_by_a_transform():
    """A metric in neither group is released at full precision, untransformed.

    tethering_data_GB_dl_sum does not end in `_GB_sum`, so a pattern anchored
    there skipped it silently.
    """
    frame = pd.DataFrame({column: [1.0] for column in DATASET_NUMERIC_COLUMNS})

    covered = set(anonymise.qoe_columns(frame)) | set(anonymise.volume_columns(frame))

    assert covered == set(DATASET_NUMERIC_COLUMNS)


def test_tethering_is_treated_as_a_volume_column():
    frame = pd.DataFrame({column: [1.0] for column in DATASET_NUMERIC_COLUMNS})

    assert "tethering_data_GB_dl_sum" in anonymise.volume_columns(frame)
    assert "tethering_data_GB_dl_sum" not in anonymise.qoe_columns(frame)


def test_rounded_release_values_have_no_long_digit_runs():
    """Full-precision floats carry tails long enough to trip the leak guard."""
    import re

    rng = np.random.default_rng(0)
    values = pd.Series(
        np.concatenate(
            [rng.uniform(0, 1, 5000), rng.uniform(0, 1e-3, 5000), rng.exponential(0.5, 5000)]
        )
    )

    rounded = anonymise.round_sig_figs(values, 3).astype(str)

    assert not [v for v in rounded.unique() if re.search(r"\d{10,}", v)]
