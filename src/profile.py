"""Aggregate profile of the raw dataset.

Emits ``outputs/profile.json``. Every statistic is an aggregate: no row, no
identifier value and no free-text sample ever reaches the output.

Run with::

    python -m src.profile
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src import safety

CATEGORICAL_COLUMNS = ("radio_access_type", "province", "application_category")
NUMERIC_COLUMNS = (
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

OUTPUT_PATH = "outputs/profile.json"


def _f(value) -> float | None:
    """Coerce to a plain, rounded float (or None) so json.dumps stays happy."""
    return safety.round_float(value)


def _i(value) -> int | None:
    return None if value is None else int(value)


def _percentiles(series: pd.Series, qs: tuple[float, ...]) -> dict[str, float | None]:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return {f"p{int(q * 100)}": None for q in qs}
    return {f"p{int(q * 100)}": _f(clean.quantile(q)) for q in qs}


def _spread(series: pd.Series) -> dict[str, float | None]:
    """min / p5 / p50 / p95 / max of a numeric series."""
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return {"min": None, "p5": None, "p50": None, "p95": None, "max": None}
    return {
        "min": _f(clean.min()),
        "p5": _f(clean.quantile(0.05)),
        "p50": _f(clean.quantile(0.50)),
        "p95": _f(clean.quantile(0.95)),
        "max": _f(clean.max()),
    }


def _base(series: pd.Series) -> dict[str, object]:
    return {
        "dtype": str(series.dtype),
        "null_rate": _f(series.isna().mean()),
        "n_distinct": _i(series.nunique(dropna=True)),
    }


# --------------------------------------------------------------------------- #
# Column profiles
# --------------------------------------------------------------------------- #


def profile_identifier(series: pd.Series) -> dict[str, object]:
    """Identifier columns: shape only, never values."""
    out = _base(series)
    values = series.dropna().astype(str)
    lengths = values.str.len()
    modes = lengths.mode()
    out.update(
        {
            "min_length": _i(lengths.min()) if not lengths.empty else None,
            "max_length": _i(lengths.max()) if not lengths.empty else None,
            "mode_length": _i(modes.iloc[0]) if not modes.empty else None,
            "share_all_digits": _f(values.str.fullmatch(r"\d+").mean()) if not values.empty else None,
        }
    )
    return out


def profile_numeric(series: pd.Series) -> dict[str, object]:
    out = _base(series)
    clean = pd.to_numeric(series, errors="coerce").dropna()
    out.update(_percentiles(series, (0.01, 0.05, 0.50, 0.95, 0.99)))
    out.update(
        {
            "min": _f(clean.min()) if not clean.empty else None,
            "max": _f(clean.max()) if not clean.empty else None,
            "share_zero": _f((clean == 0).mean()) if not clean.empty else None,
        }
    )
    return out


def profile_categorical(series: pd.Series) -> dict[str, object]:
    out = _base(series)
    counts = series.value_counts(dropna=False)
    out["value_counts"] = {
        ("<null>" if pd.isna(key) else str(key)): _i(value) for key, value in counts.items()
    }
    return out


def profile_enb(df: pd.DataFrame) -> dict[str, object]:
    series = df["enb"]
    out = _base(series)
    rows_per_enb = df.groupby("enb", observed=True).size()
    subs_per_enb = df.groupby("enb", observed=True)["msisdn"].nunique()
    out.update(
        {
            "rows_per_enb": _spread(rows_per_enb),
            "distinct_msisdn_per_enb": _spread(subs_per_enb),
            "n_enb_with_lt5_msisdn": _i((subs_per_enb < 5).sum()),
        }
    )
    return out


def profile_time(series: pd.Series) -> dict[str, object]:
    out = _base(series)
    stamps = pd.Series(sorted(series.dropna().unique()))
    gap_seconds = None
    if len(stamps) > 1:
        gaps = stamps.diff().dropna().dt.total_seconds()
        modes = gaps.mode()
        gap_seconds = _f(modes.iloc[0]) if not modes.empty else None
    out.update(
        {
            "min": str(series.min()),
            "max": str(series.max()),
            "most_common_gap_seconds": gap_seconds,
        }
    )
    return out


# --------------------------------------------------------------------------- #
# Structure
# --------------------------------------------------------------------------- #


def profile_structure(df: pd.DataFrame) -> dict[str, object]:
    """Relationships between subscriber, sim, device and time."""
    rows_per_msisdn = df.groupby("msisdn", observed=True).size()
    imsi_per_msisdn = df.groupby("msisdn", observed=True)["imsi"].nunique()
    msisdn_per_imsi = df.groupby("imsi", observed=True)["msisdn"].nunique()
    imei_per_msisdn = df.groupby("msisdn", observed=True)["imei"].nunique()
    msisdn_per_tac = df.groupby("tac", observed=True)["msisdn"].nunique()

    days = df["time_start"].dt.date
    msisdn_per_day = df.groupby(days, observed=True)["msisdn"].nunique()

    return {
        "n_rows": _i(len(df)),
        "n_msisdn": _i(df["msisdn"].nunique()),
        "rows_per_msisdn": {
            "min": _i(rows_per_msisdn.min()),
            "p50": _f(rows_per_msisdn.quantile(0.50)),
            "p95": _f(rows_per_msisdn.quantile(0.95)),
            "max": _i(rows_per_msisdn.max()),
        },
        "share_msisdn_with_multiple_imsi": _f((imsi_per_msisdn > 1).mean()),
        "share_imsi_with_multiple_msisdn": _f((msisdn_per_imsi > 1).mean()),
        "share_msisdn_with_multiple_imei": _f((imei_per_msisdn > 1).mean()),
        "tac": {
            "n_distinct": _i(df["tac"].nunique()),
            "msisdn_per_tac": _spread(msisdn_per_tac),
            "n_tac_with_lt5_msisdn": _i((msisdn_per_tac < 5).sum()),
        },
        "n_distinct_days": _i(days.nunique()),
        "msisdn_per_day_p50": _f(msisdn_per_day.quantile(0.50)),
    }


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #


def build_profile(df: pd.DataFrame) -> dict[str, object]:
    columns: dict[str, object] = {}
    for column in df.columns:
        if column == "tac":
            continue
        if column in safety.ID_COLUMNS:
            columns[column] = profile_identifier(df[column])
        elif column in NUMERIC_COLUMNS:
            columns[column] = profile_numeric(df[column])
        elif column in CATEGORICAL_COLUMNS:
            columns[column] = profile_categorical(df[column])
        elif column == "enb":
            columns[column] = profile_enb(df)
        elif column == "time_start":
            columns[column] = profile_time(df[column])
        else:
            columns[column] = _base(df[column])

    return {
        "n_rows": _i(len(df)),
        "n_columns": _i(len(df.columns) - 1),  # tac is derived, not a source column
        "columns": columns,
        "structure": profile_structure(df),
    }


def print_summary(profile: dict) -> None:
    structure = profile["structure"]
    tac = structure["tac"]
    print("=" * 62)
    print("PROFILE SUMMARY (aggregates only)")
    print("=" * 62)
    print(f"rows                       : {profile['n_rows']:,}")
    print(f"source columns             : {profile['n_columns']}")
    print(f"distinct msisdn            : {structure['n_msisdn']:,}")
    print(
        "rows per msisdn            : "
        f"min {structure['rows_per_msisdn']['min']}, "
        f"p50 {structure['rows_per_msisdn']['p50']:.0f}, "
        f"p95 {structure['rows_per_msisdn']['p95']:.0f}, "
        f"max {structure['rows_per_msisdn']['max']}"
    )
    print(f"msisdn with >1 imsi        : {structure['share_msisdn_with_multiple_imsi']:.4%}")
    print(f"imsi with >1 msisdn        : {structure['share_imsi_with_multiple_msisdn']:.4%}")
    print(f"msisdn with >1 imei        : {structure['share_msisdn_with_multiple_imei']:.4%}")
    print(f"distinct tac               : {tac['n_distinct']:,}  (<5 msisdn: {tac['n_tac_with_lt5_msisdn']:,})")
    enb = profile["columns"]["enb"]
    print(f"distinct enb               : {enb['n_distinct']:,}  (<5 msisdn: {enb['n_enb_with_lt5_msisdn']:,})")
    print(f"distinct days              : {structure['n_distinct_days']}")
    print(f"msisdn per day (p50)       : {structure['msisdn_per_day_p50']:.0f}")
    time_col = profile["columns"]["time_start"]
    print(f"time range                 : {time_col['min']} .. {time_col['max']}")
    print(f"distinct timestamps        : {time_col['n_distinct']:,} (modal gap {time_col['most_common_gap_seconds']:.0f}s)")
    print("=" * 62)


@safety.safe_main
def main() -> None:
    df = safety.add_tac(safety.load_raw())
    profile = build_profile(df)
    path = safety.safe_write_json(profile, OUTPUT_PATH)
    print_summary(profile)
    print(f"written: {path}")


if __name__ == "__main__":
    main()
