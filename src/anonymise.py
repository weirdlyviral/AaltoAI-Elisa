"""M2 - anonymisation method.

Produces up to three releases from the raw extract, each a different point on
the linkability scale:

* **record**    - no subscriber link at all.
* **session**   - a within-release ``session_id`` under an ephemeral HMAC key.
* **aggregate** - counts and distributions per (bucket, province, RAT, app).

The subscriber key is held in an internal ``_subscriber`` column that is dropped
before any write; ``safe_write_df`` is the backstop if that ever fails.

Run with::

    python -m src.anonymise --mode all
    python -m src.anonymise --sweep
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import re
from dataclasses import asdict, dataclass, field as dataclass_field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src import safety

RELEASE_CONFIG_PATH = Path("config/release.yaml")
FIELDS_YAML_PATH = Path("config/fields.yaml")
RELEASES_DIR = Path("outputs/releases")
TRANSFORM_LOG_PATH = Path("outputs/transform_log.json")
RELEASE_STATS_PATH = Path("outputs/release_stats.json")
SWEEP_PATH = Path("outputs/sweep.json")
TRANSFORMATIONS_DOC_PATH = Path("docs/transformations.md")

#: Dropped outright - see transform 1.
IDENTIFIER_COLUMNS = ("msisdn", "imsi", "imei", "tac")
#: Internal subscriber key. Never written; stripped before every release.
SUBSCRIBER = "_subscriber"

#: Quasi-identifiers that define a k-anonymity group for record/session.
QI_COLUMNS = ["time_bucket", "area", "radio_access_type", "application_category"]
#: Grouping keys for the aggregate release.
AGGREGATE_KEYS = ["time_bucket", "province", "radio_access_type", "application_category"]
#: Slice within which secondary suppression is applied, so a primary-suppressed
#: cell cannot be recovered by subtracting the survivors from a known total.
AGGREGATE_SLICE_KEYS = ["time_bucket", "province"]
#: Count columns that receive Laplace noise when dp_epsilon is set.
DP_NOISED_COLUMNS = ("n_subscribers",)

QOE_PATTERN = re.compile(r"^(tp_|.*_rtt_|tcp_retrans_|http_)")
# Must match tethering_data_GB_dl_sum as well as the plain *_GB_sum columns -
# a pattern anchored on "_GB_sum$" silently skips it, leaving it untransformed.
VOLUME_PATTERN = re.compile(r"_GB_[a-z_]*sum$")

RARE_CATEGORY_COLUMNS = ("radio_access_type", "application_category")

# Aggregate is the headline release; record is published alongside it for
# comparison. Session linkage is optional and must be asked for explicitly.
MODES = ("aggregate", "record", "session")
DEFAULT_MODES = ("aggregate", "record")
OPTIONAL_MODES = ("session",)


# --------------------------------------------------------------------------- #
# Transform log
# --------------------------------------------------------------------------- #


@dataclass
class TransformEntry:
    """One logged transformation."""

    field: str
    action: str
    params: dict[str, Any]
    rows_affected: int
    rationale: str = ""


@dataclass
class TransformLog:
    entries: list[TransformEntry] = dataclass_field(default_factory=list)

    def add(
        self,
        field: str,
        action: str,
        params: dict[str, Any] | None = None,
        rows_affected: int = 0,
        rationale: str = "",
    ) -> None:
        self.entries.append(
            TransformEntry(field, action, params or {}, int(rows_affected), rationale)
        )

    def as_list(self) -> list[dict[str, Any]]:
        return [asdict(entry) for entry in self.entries]


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


def load_release_config(path: Path = RELEASE_CONFIG_PATH) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"{path} not found.")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def qoe_columns(df: pd.DataFrame) -> list[str]:
    return [
        c
        for c in df.columns
        if QOE_PATTERN.match(c)
        and not VOLUME_PATTERN.search(c)
        and pd.api.types.is_numeric_dtype(df[c])
    ]


def volume_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if VOLUME_PATTERN.search(c)]


# --------------------------------------------------------------------------- #
# Numeric helpers
# --------------------------------------------------------------------------- #


def round_sig_figs(series: pd.Series, digits: int) -> pd.Series:
    """Round to N significant figures, preserving NaN and exact zeros.

    Significant-figure rounding also keeps digit runs short, which is what lets
    these columns pass the leak guard's ``\\d{10,}`` rule. That holds while
    values stay below 1e9; above it even 3 significant figures render a
    10-digit integer part and the guard will (correctly) refuse the write
    until someone decides on a unit change. This extract peaks at 2.9e6.
    """
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    out = values.copy()
    usable = np.isfinite(values) & (values != 0)
    if usable.any():
        subset = values[usable]
        magnitude = np.floor(np.log10(np.abs(subset))).astype(int)
        decimals = digits - 1 - magnitude
        rounded = np.empty_like(subset)
        # np.round(x, d) lands on the nearest double to a clean decimal, so the
        # shortest repr stays short. Scaling by hand (x * f / f) does not: it
        # leaves values like 0.30000000000000004, whose 17-digit tail trips the
        # leak guard. decimals varies per element, and np.round needs a scalar,
        # so the work is grouped by magnitude.
        for decimal in np.unique(decimals):
            mask = decimals == decimal
            rounded[mask] = np.round(subset[mask], int(decimal))
        out[usable] = rounded
    return pd.Series(out, index=series.index)


def native_bucket_minutes(df: pd.DataFrame) -> int:
    """Most common gap between distinct timestamps, in whole minutes."""
    stamps = pd.Series(sorted(df["time_start"].dropna().unique()))
    if len(stamps) < 2:
        return 1
    gaps = stamps.diff().dropna().dt.total_seconds()
    modes = gaps.mode()
    if modes.empty:
        return 1
    return max(1, int(round(float(modes.iloc[0]) / 60.0)))


def effective_bucket_minutes(df: pd.DataFrame, configured: int | None) -> tuple[int, int]:
    """Return (effective, native). The native window wins when it is coarser."""
    native = native_bucket_minutes(df)
    if configured is None:
        return native, native
    return max(int(configured), native), native


# --------------------------------------------------------------------------- #
# Transforms 1-6
# --------------------------------------------------------------------------- #


def drop_identifiers(df: pd.DataFrame, log: TransformLog) -> pd.DataFrame:
    """Transform 1: drop the direct identifiers and the device code."""
    work = df.copy()
    work[SUBSCRIBER] = work["msisdn"].astype("string")
    for column in IDENTIFIER_COLUMNS:
        if column in work.columns:
            work = work.drop(columns=[column])
            log.add(
                column,
                "dropped",
                {},
                len(work),
                "Direct identifier; on real data tac would become a device class."
                if column == "tac"
                else "Direct identifier, removed before any release.",
            )
    return work


def bucket_time(df: pd.DataFrame, minutes: int, native: int, log: TransformLog) -> pd.DataFrame:
    """Transform 2: time_start -> time_bucket."""
    work = df.copy()
    work["time_bucket"] = work["time_start"].dt.floor(f"{minutes}min")
    work = work.drop(columns=["time_start"])
    log.add(
        "time_start",
        "floored to time_bucket",
        {"time_bucket_minutes": minutes, "native_window_minutes": native},
        len(work),
        "Coarsens the timestamp so a cell visit is not pinpointed to the second.",
    )
    return work


def build_area(
    df: pd.DataFrame, config: dict[str, Any], log: TransformLog
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Transform 3: enb -> area, with rare cells folded into <province>_OTHER."""
    work = df.copy()
    mode = config["area_mode"]
    minimum = int(config["min_subscribers_per_area"])

    if mode == "province":
        work["area"] = work["province"].astype(str)
        work = work.drop(columns=["enb"])
        log.add(
            "enb",
            "replaced by province",
            {"area_mode": mode},
            len(work),
            "Location generalised to province; the cell is never released.",
        )
        return work, {}

    if mode != "enb_tokenised":
        raise ValueError(f"Unknown area_mode: {mode!r}")

    subs_per_enb = work.groupby("enb", observed=True)[SUBSCRIBER].nunique()
    rare = set(subs_per_enb[subs_per_enb < minimum].index)
    is_rare = work["enb"].isin(rare)

    # Random token order, seeded so a run is reproducible. The map is in memory
    # only and is never written; see docs/transformations.md for the limitation.
    keep = sorted(str(e) for e in subs_per_enb.index if e not in rare)
    rng = np.random.default_rng(safety.SEED)
    order = rng.permutation(len(keep))
    token_map = {enb: f"A{order[i] + 1:04d}" for i, enb in enumerate(keep)}

    area = work["enb"].astype(str).map(token_map)
    area = area.where(~is_rare, work["province"].astype(str) + "_OTHER")
    work["area"] = area
    work = work.drop(columns=["enb"])

    log.add(
        "enb",
        "rare cells folded into <province>_OTHER",
        {"min_subscribers_per_area": minimum, "n_rare_cells": len(rare)},
        int(is_rare.sum()),
        "A cell with few subscribers is close to an identifier on its own.",
    )
    log.add(
        "enb",
        "remaining cells replaced by random tokens",
        {"area_mode": mode, "n_tokens": len(token_map)},
        int((~is_rare).sum()),
        "Token order is random and the map is never persisted.",
    )
    return work, token_map


def fold_rare_categories(
    df: pd.DataFrame, config: dict[str, Any], log: TransformLog
) -> pd.DataFrame:
    """Transform 4: rare categorical values -> OTHER."""
    work = df.copy()
    minimum = int(config["rare_category_min_subscribers"])
    for column in RARE_CATEGORY_COLUMNS:
        if column not in work.columns:
            continue
        subs = work.groupby(column, observed=True)[SUBSCRIBER].nunique()
        rare = set(subs[subs < minimum].index)
        if not rare:
            log.add(column, "no rare categories", {"min_subscribers": minimum}, 0, "")
            continue
        mask = work[column].isin(rare)
        work.loc[mask, column] = "OTHER"
        log.add(
            column,
            "rare categories folded into OTHER",
            {"min_subscribers": minimum, "n_rare_values": len(rare)},
            int(mask.sum()),
            "A category held by few subscribers singles them out.",
        )
    return work


def winsorise_qoe(df: pd.DataFrame, config: dict[str, Any], log: TransformLog) -> pd.DataFrame:
    """Transform 5: winsorise QoE metrics to [p01, p99] and round."""
    work = df.copy()
    lower, upper = config["numeric_winsorise"]
    lower = float(lower)
    upper = float(upper)
    digits = int(config["numeric_round_sig_figs"])

    for column in qoe_columns(work):
        series = pd.to_numeric(work[column], errors="coerce")
        bounds = series.quantile([lower, upper])
        work[column] = round_sig_figs(series.clip(lower=bounds.iloc[0], upper=bounds.iloc[1]), digits)
        log.add(
            column,
            "winsorised and rounded",
            {"lower_quantile": lower, "upper_quantile": upper, "significant_figures": digits},
            int((series < bounds.iloc[0]).sum() + (series > bounds.iloc[1]).sum()),
            "Limits outlier influence on medians. WARNING: Means are NOT a supported statistic for QoE metrics (heavy tails); use medians/percentiles.",
        )
    return work


def top_code_volumes(df: pd.DataFrame, config: dict[str, Any], log: TransformLog) -> pd.DataFrame:
    """Transform 6: top-code volume fields and round."""
    work = df.copy()
    digits = int(config["numeric_round_sig_figs"])
    for column in volume_columns(work):
        series = pd.to_numeric(work[column], errors="coerce")
        non_zero = series[series > 0]
        cap = non_zero.quantile(0.99) if not non_zero.empty else 0.0
        affected = int((series > cap).sum())
        work[column] = round_sig_figs(series.clip(upper=cap), digits)
        log.add(
            column,
            "top-coded at non-zero p99 and rounded",
            {"quantile": 0.99, "significant_figures": digits, "cap": safety.round_float(cap)},
            affected,
            "Heavy users are outliers and are identifiable by volume alone.",
        )
    return work


# --------------------------------------------------------------------------- #
# Transform 7 - k-anonymity
# --------------------------------------------------------------------------- #


def _group_subscriber_counts(df: pd.DataFrame, qi: list[str]) -> pd.Series:
    return df.groupby(qi, observed=True, dropna=False)[SUBSCRIBER].transform("nunique")


def enforce_k_anonymity(
    df: pd.DataFrame, k: int, log: TransformLog | None = None
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Transform 7: escalate area to province, then suppress what still fails.

    k counts DISTINCT SUBSCRIBERS, so one chatty subscriber can never satisfy k
    on their own.
    """
    work = df.copy()
    rows_in = len(work)
    qi = [c for c in QI_COLUMNS if c in work.columns]

    sizes = _group_subscriber_counts(work, qi)
    violating = sizes < k
    n_escalated = int(violating.sum())
    if n_escalated and "province" in work.columns:
        work.loc[violating, "area"] = work.loc[violating, "province"].astype(str)

    sizes = _group_subscriber_counts(work, qi)
    still_violating = sizes < k
    n_suppressed = int(still_violating.sum())
    work = work.loc[~still_violating].copy()

    final_sizes = _group_subscriber_counts(work, qi) if len(work) else pd.Series(dtype=float)
    stats = {
        "k": k,
        "qi_columns": qi,
        "rows_in": rows_in,
        "rows_out": len(work),
        "rows_escalated_to_province": n_escalated,
        "rows_suppressed": n_suppressed,
        "pct_escalated": safety.round_float(100.0 * n_escalated / rows_in) if rows_in else 0.0,
        "pct_suppressed": safety.round_float(100.0 * n_suppressed / rows_in) if rows_in else 0.0,
        "min_subscribers_per_group": int(final_sizes.min()) if len(final_sizes) else 0,
        "median_subscribers_per_group": safety.round_float(final_sizes.median())
        if len(final_sizes)
        else 0.0,
        "n_qi_groups": int(work.groupby(qi, observed=True, dropna=False).ngroups) if len(work) else 0,
    }

    if log is not None:
        log.add(
            "area",
            "escalated to province for groups below k",
            {"k": k, "qi_columns": qi},
            n_escalated,
            "Coarsening location rescues rows that would otherwise be dropped.",
        )
        log.add(
            ", ".join(qi),
            "rows suppressed for still being below k",
            {"k": k},
            n_suppressed,
            "Last resort once generalisation cannot reach k distinct subscribers.",
        )
    return work, stats


# --------------------------------------------------------------------------- #
# Modes
# --------------------------------------------------------------------------- #


def add_session_id(df: pd.DataFrame, log: TransformLog) -> pd.DataFrame:
    """Session mode: pseudonym under an ephemeral key that is destroyed here.

    The digest is emitted as two 8-character groups. 16 unbroken hex characters
    are all digits often enough (~1 in 11k, so several times across 200k
    subscribers) to trip the leak guard's ``\\d{10,}`` rule; a separator makes
    that impossible without losing entropy.
    """
    work = df.copy()
    key = os.urandom(32)
    try:
        digests = {
            subscriber: hmac.new(key, str(subscriber).encode("utf-8"), hashlib.sha256).hexdigest()
            for subscriber in work[SUBSCRIBER].dropna().unique()
        }
    finally:
        # The key never leaves this function: not written, not logged, not returned.
        key = b"\x00" * 32
        del key

    work["session_id"] = work[SUBSCRIBER].map(
        lambda s: f"{digests[s][:8]}-{digests[s][8:16]}" if pd.notna(s) else ""
    )
    log.add(
        "msisdn",
        "replaced by session_id (HMAC-SHA256, ephemeral key)",
        {"scope": "this release only", "digest_hex_chars": 16},
        len(work),
        "Links a subscriber's rows within the release without a persistent id.",
    )
    return work


def aggregate_cells(
    df: pd.DataFrame, config: dict[str, Any], log: TransformLog, epsilon: float | None = None, scale: float | None = None
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build the aggregate at ONE granularity, with primary + secondary suppression."""
    keys = [c for c in AGGREGATE_KEYS if c in df.columns]
    minimum = int(config["aggregate_min_subscribers_per_cell"])

    grouped = df.groupby(keys, observed=True, dropna=False)
    # We no longer calculate n_rows for DP, it was dropped.
    out = grouped.agg(n_subscribers=(SUBSCRIBER, "nunique"))
    for column in qoe_columns(df):
        out[f"{column}_p10"] = grouped[column].quantile(0.10)
        out[f"{column}_median"] = grouped[column].median()
        out[f"{column}_p90"] = grouped[column].quantile(0.90)
    for column in volume_columns(df):
        out[f"{column}_total"] = grouped[column].sum()
    out = out.reset_index()
    cells_in = len(out)
    
    true_counts = out[["n_subscribers"]].copy()

    # APPLY NOISE BEFORE SUPPRESSION!
    out, dp_stats = apply_dp_noise(out, epsilon, scale, log)

    primary = out["n_subscribers"] < minimum
    n_primary = int(primary.sum())

    secondary = pd.Series(False, index=out.index)
    slice_keys = [c for c in AGGREGATE_SLICE_KEYS if c in out.columns]
    if slice_keys and n_primary:
        affected = {
            tuple(str(v) for v in row)
            for row in out.loc[primary, slice_keys].to_numpy()
        }
        survivors = out.loc[~primary]
        victims = []
        for slice_value, group in survivors.groupby(slice_keys, observed=True, dropna=False):
            parts = slice_value if isinstance(slice_value, tuple) else (slice_value,)
            if tuple(str(v) for v in parts) in affected:
                victims.append(group["n_subscribers"].idxmin())
        secondary.loc[victims] = True

    n_secondary = int(secondary.sum())
    suppressed = primary | secondary
    out = out.loc[~suppressed].copy()

    log.add(
        "aggregate cells",
        "primary suppression: cells below the subscriber minimum",
        {"aggregate_min_subscribers_per_cell": minimum},
        n_primary,
        "A thin cell describes too few people to publish.",
    )
    log.add(
        "aggregate cells",
        "secondary suppression: smallest survivor in an affected slice",
        {"slice_keys": slice_keys},
        n_secondary,
        "Stops a primary-suppressed cell being recovered by subtraction.",
    )

    stats = {
        "granularity": keys,
        "single_granularity_only": True,
        "cells_in": cells_in,
        "cells_out": len(out),
        "cells_suppressed_primary": n_primary,
        "cells_suppressed_secondary": n_secondary,
        "cells_suppressed": n_primary + n_secondary,
        "pct_cells_suppressed": safety.round_float(
            100.0 * (n_primary + n_secondary) / cells_in
        )
        if cells_in
        else 0.0,
        "min_subscribers_per_cell": int(out["n_subscribers"].min()) if len(out) else 0,
        "median_subscribers_per_cell": safety.round_float(out["n_subscribers"].median())
        if len(out)
        else 0.0,
        "dp": dp_stats,
        "true_counts_for_error": true_counts.loc[out.index] if not out.empty else true_counts.iloc[0:0]
    }
    return out, stats


def apply_dp_noise(
    out: pd.DataFrame, epsilon: float | None, scale: float | None, log: TransformLog | None = None
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Add Laplace noise to the published counts."""
    if not epsilon or not scale:
        return out, {
            "applied": False,
            "epsilon": None,
            "noise_scale": None,
            "mechanism": None,
        }

    rng = np.random.default_rng(safety.SEED)
    work = out.copy()
    for column in DP_NOISED_COLUMNS:
        if column not in work.columns:
            continue
        noisy = work[column].to_numpy(dtype=float) + rng.laplace(0.0, scale, size=len(work))
        work[column] = np.maximum(0, np.round(noisy)).astype(int)

    stats = {
        "applied": True,
        "epsilon": float(epsilon),
        "noise_scale": safety.round_float(scale),
        "mechanism": "Laplace",
        "seed": safety.SEED,
        "noised_columns": list(DP_NOISED_COLUMNS),
        "assumed_sensitivity": scale * float(epsilon) if scale and epsilon else 1.0,
        "caveats": [
            "Cell suppression is decided on noisy counts.",
        ],
    }
    if log is not None:
        log.add(
            ", ".join(DP_NOISED_COLUMNS),
            "Laplace noise added to counts",
            {"dp_epsilon": float(epsilon), "noise_scale": scale, "seed": safety.SEED},
            len(work),
            "Blurs exact counts so one subscriber cannot be differenced out.",
        )
    return work, stats


def count_relative_error(true_frame: pd.DataFrame, noisy_frame: pd.DataFrame) -> dict[str, Any]:
    """|noisy - true| / true per noised count column, as median and mean.

    The median alone is misleading at larger epsilon: Laplace noise at scale 0.5
    rounds to zero for more than half the cells, so the median reads 0.0 while
    the tail still moves. The mean is reported next to it for that reason.
    """
    errors: dict[str, Any] = {}
    for column in DP_NOISED_COLUMNS:
        if column not in true_frame.columns or column not in noisy_frame.columns:
            continue
        true = true_frame[column].to_numpy(dtype=float)
        noisy = noisy_frame[column].to_numpy(dtype=float)
        usable = true > 0
        if not usable.any():
            errors[f"median_rel_error_{column}"] = None
            errors[f"mean_rel_error_{column}"] = None
            continue
        relative = np.abs(noisy[usable] - true[usable]) / true[usable]
        errors[f"median_rel_error_{column}"] = safety.round_float(float(np.median(relative)))
        errors[f"mean_rel_error_{column}"] = safety.round_float(float(np.mean(relative)))
    return errors


def build_aggregate(
    df: pd.DataFrame, config: dict[str, Any], log: TransformLog
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Aggregate mode: the headline release."""
    digits = int(config["numeric_round_sig_figs"])
    
    # 1. Contribution Bounding to calculate scale
    keys = [c for c in AGGREGATE_KEYS if c in df.columns]
    max_cells = 1
    if keys and SUBSCRIBER in df.columns:
        cells_per_sub = df.drop_duplicates([SUBSCRIBER] + keys).groupby(SUBSCRIBER, observed=True).size()
        max_cells = int(config.get("max_cells_per_subscriber", cells_per_sub.quantile(0.99) if not cells_per_sub.empty else 1))
        # Log max_cells as part of config if not present
        if "max_cells_per_subscriber" not in config:
            config["max_cells_per_subscriber"] = max_cells

    epsilon = config.get("dp_epsilon")
    scale = (max_cells / float(epsilon)) if epsilon else None

    # Cells are built and noised inside aggregate_cells now
    noisy, stats = aggregate_cells(df, config, log, epsilon=epsilon, scale=scale)
    
    dp_stats = stats["dp"]
    if dp_stats["applied"]:
        true_counts = stats.pop("true_counts_for_error")
        stats["count_error"] = count_relative_error(true_counts, noisy)

    for column in noisy.columns:
        if pd.api.types.is_float_dtype(noisy[column]):
            noisy[column] = round_sig_figs(noisy[column], digits)
    return noisy, stats


# --------------------------------------------------------------------------- #
# Final assertions
# --------------------------------------------------------------------------- #


def assert_release_safe(
    df: pd.DataFrame, mode: str, k: int, raw_enb: set[str], tokenised: bool
) -> None:
    """Refuse to write anything that fails the M2 guarantees."""
    banned = [c for c in (*IDENTIFIER_COLUMNS, SUBSCRIBER) if c in df.columns]
    if banned:
        raise safety.LeakError(f"{mode}: identifier column(s) still present: {banned}")

    if mode in ("record", "session"):
        qi = [c for c in QI_COLUMNS if c in df.columns]
        if SUBSCRIBER in df.columns:  # pragma: no cover - covered by the check above
            raise safety.LeakError(f"{mode}: subscriber key present")
        # Group sizes are recomputed from session_id where available; for record
        # mode the check is done before the key is dropped (see build_release).
        if not qi:
            raise safety.LeakError(f"{mode}: no quasi-identifier columns present")

    if tokenised and "area" in df.columns:
        overlap = set(df["area"].dropna().astype(str).unique()) & raw_enb
        if overlap:
            raise safety.LeakError(
                f"{mode}: {len(overlap)} raw enb value(s) survived into 'area'"
            )


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #


def prepare(
    df: pd.DataFrame, config: dict[str, Any], log: TransformLog
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Transforms 1-6, shared by every mode."""
    bucket, native = effective_bucket_minutes(df, config.get("time_bucket_minutes"))
    work = drop_identifiers(df, log)
    work = bucket_time(work, bucket, native, log)
    work, _token_map = build_area(work, config, log)
    work = fold_rare_categories(work, config, log)
    work = winsorise_qoe(work, config, log)
    work = top_code_volumes(work, config, log)
    return work, {"time_bucket_minutes": bucket, "native_window_minutes": native}


def build_release(
    prepared: pd.DataFrame, mode: str, config: dict[str, Any], log: TransformLog
) -> tuple[pd.DataFrame, dict[str, Any], pd.Series | None]:
    k = int(config["k"])

    if mode == "aggregate":
        out, stats = build_aggregate(prepared, config, log)
        return out, stats, None

    work, stats = enforce_k_anonymity(prepared, k, log)
    if mode == "session":
        work = add_session_id(work, log)
        
    eval_index = work[SUBSCRIBER].copy()
    work = work.drop(columns=[SUBSCRIBER])
    log.add(SUBSCRIBER, "internal key dropped before write", {}, len(work), "Never released.")
    return work, stats, eval_index


# --------------------------------------------------------------------------- #
# Documentation
# --------------------------------------------------------------------------- #


def render_transformations_doc(
    config: dict[str, Any], log: TransformLog, stats: dict[str, Any]
) -> str:
    """Deterministic markdown from config + transform log."""
    lines = [
        "# Transformations",
        "",
        "Generated by `python -m src.anonymise`. Do not edit by hand.",
        "",
        "## Parameters",
        "",
        "| parameter | value |",
        "| --- | --- |",
    ]
    for key in sorted(config):
        lines.append(f"| `{key}` | `{config[key]}` |")

    lines += [
        "",
        "## Transformations applied",
        "",
        "| output column | source column | transformation | parameters | rationale | rows affected |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for entry in log.entries:
        params = ", ".join(f"{k}={v}" for k, v in entry.params.items()) or "-"
        lines.append(
            f"| {_output_column_for(entry)} | {entry.field} | {entry.action} | "
            f"{params} | {entry.rationale or '-'} | {entry.rows_affected:,} |"
        )

    lines += ["", "## Suppressed rows", ""]
    for mode, mode_stats in sorted(stats.get("modes", {}).items()):
        if "rows_suppressed" in mode_stats:
            lines.append(
                f"- **{mode}**: {mode_stats['rows_suppressed']:,} rows suppressed "
                f"({mode_stats['pct_suppressed']}%), "
                f"{mode_stats['rows_escalated_to_province']:,} rows escalated to province "
                f"({mode_stats['pct_escalated']}%); "
                f"min {mode_stats['min_subscribers_per_group']} distinct subscribers per QI group."
            )
        elif "cells_suppressed" in mode_stats:
            lines.append(
                f"- **{mode}**: {mode_stats['cells_suppressed']:,} of "
                f"{mode_stats['cells_in']:,} cells suppressed "
                f"({mode_stats['pct_cells_suppressed']}%) - "
                f"{mode_stats['cells_suppressed_primary']:,} primary "
                f"(below the subscriber minimum) and "
                f"{mode_stats['cells_suppressed_secondary']:,} secondary "
                f"(smallest survivor in an affected slice)."
            )
            dp = mode_stats.get("dp", {})
            if dp.get("applied"):
                lines.append(
                    f"- **{mode} noise**: Laplace, epsilon {dp['epsilon']}, scale "
                    f"{dp['noise_scale']}, seed {dp['seed']}, applied to "
                    f"{', '.join(dp['noised_columns'])}."
                )

    lines += [
        "",
        "## Assumptions and limitations",
        "",
        "- The extract covers a single hour on one date, so no cross-day linkage is",
        "  possible here and longitudinal risk is untested.",
        "- `tac` is constant across every subscriber in this extract, so device-model",
        "  risk cannot be measured from it.",
        "- Area tokens are assigned under seed 42 for reproducibility. Anyone holding",
        "  both the raw extract and this code can rebuild the token map, so",
        "  tokenisation protects an external recipient, not Elisa as the source holder.",
        "- The session key is ephemeral and destroyed after use, so `session_id` cannot",
        "  be re-derived, but it does link a subscriber's rows within the release.",
        "- Aggregates are published at one granularity only. No marginals or slice",
        "  totals are released, and within any slice that lost a cell the smallest",
        "  survivor is suppressed too, so a suppressed cell cannot be differenced out.",
        "- The Laplace scale assumes sensitivity 1. That holds for `n_subscribers`;",
        "  `n_rows` has a higher user-level sensitivity, so the stated epsilon is not",
        "  a strict user-level guarantee for that column.",
        "- Which cells are suppressed is decided on true counts, so the published",
        "  cell set is not itself covered by epsilon.",
        "",
    ]
    return "\n".join(lines)


def _output_column_for(entry: TransformEntry) -> str:
    if entry.action.startswith("dropped") or "dropped" in entry.action:
        return "(removed)"
    if entry.field == "time_start":
        return "time_bucket"
    if entry.field == "enb":
        return "area"
    if entry.field == "msisdn":
        return "session_id"
    if entry.field == "area":
        return "area"
    return entry.field


def update_fields_yaml(log: TransformLog, config: dict[str, Any]) -> Path:
    """Fill the treatment field for every entry in config/fields.yaml."""
    fields = yaml.safe_load(FIELDS_YAML_PATH.read_text(encoding="utf-8"))
    treatments: dict[str, list[str]] = {}
    for entry in log.entries:
        for name in (part.strip() for part in entry.field.split(",")):
            treatments.setdefault(name, []).append(entry.action)

    for name, meta in fields.items():
        if name in treatments:
            meta["treatment"] = "; ".join(dict.fromkeys(treatments[name]))
        elif name == "province":
            meta["treatment"] = "kept; also the escalation target for area"
        else:
            meta["treatment"] = "kept as is"

    text = (
        "# Field treatment plan. 'class' is the reviewed privacy class;\n"
        "# 'treatment' is filled in by src/anonymise.py (M2).\n"
        + yaml.safe_dump(fields, sort_keys=False, default_flow_style=False)
    )
    return safety.safe_write_text(text, FIELDS_YAML_PATH)


# --------------------------------------------------------------------------- #
# Sweep
# --------------------------------------------------------------------------- #

SWEEP_BUCKETS: tuple[int | None, ...] = (None, 15, 30, 60)
SWEEP_AREA_MODES = ("enb_tokenised", "province")
SWEEP_K = (5, 10, 20)
#: Epsilons swept for the aggregate release. None = publish exact counts.
SWEEP_EPSILONS: tuple[float | None, ...] = (0.5, 1.0, 2.0, None)


def run_record_sweep(df: pd.DataFrame, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Record mode over bucket x area_mode x k. Writes no releases."""
    results: list[dict[str, Any]] = []
    for bucket in SWEEP_BUCKETS:
        for area_mode in SWEEP_AREA_MODES:
            combo_config = dict(config, time_bucket_minutes=bucket, area_mode=area_mode)
            log = TransformLog()
            prepared, meta = prepare(df, combo_config, log)
            for k in SWEEP_K:
                _, stats = enforce_k_anonymity(prepared, k)
                results.append(
                    {
                        "time_bucket": "native" if bucket is None else bucket,
                        "effective_bucket_minutes": meta["time_bucket_minutes"],
                        "area_mode": area_mode,
                        "k": k,
                        "pct_rows_suppressed": stats["pct_suppressed"],
                        "pct_rows_escalated": stats["pct_escalated"],
                        "n_qi_groups": stats["n_qi_groups"],
                        "median_subscribers_per_group": stats["median_subscribers_per_group"],
                        "min_subscribers_per_group": stats["min_subscribers_per_group"],
                    }
                )
    return results


def run_aggregate_sweep(df: pd.DataFrame, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Aggregate mode over dp_epsilon. Suppression now depends on noisy counts, so we must recalculate."""
    results = []
    
    # 1. Calculate max_cells once for the sweep on PREPARED data
    log = TransformLog()
    prepared, _ = prepare(df, config, log)
    
    keys = [c for c in AGGREGATE_KEYS if c in prepared.columns]
    if keys and SUBSCRIBER in prepared.columns:
        cells_per_sub = prepared.drop_duplicates([SUBSCRIBER] + keys).groupby(SUBSCRIBER, observed=True).size()
        max_cells = int(config.get("max_cells_per_subscriber", cells_per_sub.quantile(0.99) if not cells_per_sub.empty else 1))
    else:
        max_cells = 1
        
    sweep_config = config.copy()
    sweep_config["max_cells_per_subscriber"] = max_cells

    for epsilon_str in ["0.5", "1.0", "2.0", "none"]:
        epsilon = None if epsilon_str == "none" else float(epsilon_str)
        sweep_config["dp_epsilon"] = epsilon
        
        mode_log = TransformLog()
        noisy, stats = build_aggregate(prepared.copy(), sweep_config, mode_log)
        
        dp_stats = stats["dp"]
        errors = stats.get("count_error", {})
        if not dp_stats.get("applied"):
            errors = {f"median_rel_error_{c}": 0.0 for c in DP_NOISED_COLUMNS}
            errors.update({f"mean_rel_error_{c}": 0.0 for c in DP_NOISED_COLUMNS})
        results.append(
            {
                "dp_epsilon": "none" if epsilon is None else epsilon,
                "noise_scale": dp_stats.get("noise_scale"),
                "cells_in": stats["cells_in"],
                "cells_out": stats["cells_out"],
                "pct_cells_suppressed": stats["pct_cells_suppressed"],
                "cells_suppressed_primary": stats["cells_suppressed_primary"],
                "cells_suppressed_secondary": stats["cells_suppressed_secondary"],
                "median_subscribers_per_cell": stats["median_subscribers_per_cell"],
                **errors,
            }
        )
    return results


def run_sweep(df: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    """Both sweeps. Writes no releases."""
    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "seed": safety.SEED,
        "record": {
            "grid": {
                "time_bucket": ["native", 15, 30, 60],
                "area_mode": list(SWEEP_AREA_MODES),
                "k": list(SWEEP_K),
            },
            "results": run_record_sweep(df, config),
        },
        "aggregate": {
            "grid": {"dp_epsilon": ["0.5", "1.0", "2.0", "none"]},
            "results": run_aggregate_sweep(df, config),
        },
    }


def print_sweep_table(sweep: dict[str, Any]) -> None:
    header = (
        f"{'bucket':>8} {'area_mode':<15} {'k':>3} {'%suppressed':>12} "
        f"{'%escalated':>11} {'QI groups':>10} {'med subs/grp':>13}"
    )
    print("=" * len(header))
    print("PARAMETER SWEEP - record mode")
    print("=" * len(header))
    print(header)
    print("-" * len(header))
    record_results = sweep["record"]["results"]
    for row in record_results:
        print(
            f"{str(row['time_bucket']):>8} {row['area_mode']:<15} {row['k']:>3} "
            f"{row['pct_rows_suppressed']:>12} {row['pct_rows_escalated']:>11} "
            f"{row['n_qi_groups']:>10,} {row['median_subscribers_per_group']:>13}"
        )
    print("-" * len(header))
    under5 = [r for r in record_results if (r["pct_rows_suppressed"] or 0) < 5.0]
    print(f"combinations with suppression < 5%: {len(under5)} of {len(record_results)}")

    agg_header = (
        f"{'dp_epsilon':>10} {'scale':>7} {'cells out':>10} {'%suppressed':>12} "
        f"{'primary':>8} {'secondary':>10} {'med subs/cell':>14} "
        f"{'med rel err':>12} {'mean rel err':>13}"
    )
    print()
    print("=" * len(agg_header))
    print("PARAMETER SWEEP - aggregate mode (headline release)")
    print("=" * len(agg_header))
    print(agg_header)
    print("-" * len(agg_header))
    for row in sweep["aggregate"]["results"]:
        print(
            f"{str(row['dp_epsilon']):>10} {str(row['noise_scale']):>7} "
            f"{row['cells_out']:>10,} {row['pct_cells_suppressed']:>12} "
            f"{row['cells_suppressed_primary']:>8} {row['cells_suppressed_secondary']:>10} "
            f"{str(row['median_subscribers_per_cell']):>14} "
            f"{str(row['median_rel_error_n_subscribers']):>12} "
            f"{str(row['mean_rel_error_n_subscribers']):>13}"
        )
    print("-" * len(agg_header))
    print(
        "Suppression is decided on NOISY counts, so the published cell set is "
        "covered by epsilon - and varies with it."
    )
    print("Relative error columns are for n_subscribers; n_rows is in sweep.json.")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


@safety.safe_main
def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.anonymise")
    parser.add_argument(
        "--mode",
        choices=(*MODES, "all"),
        default="all",
        help=(
            "all = aggregate + record (the published set). 'session' is optional "
            "and is only built when named explicitly."
        ),
    )
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="Run the parameter sweep (record mode only); writes no releases.",
    )
    args = parser.parse_args(argv)

    config = load_release_config()
    print("Loading raw data...")
    raw = safety.add_tac(safety.load_raw())

    if args.sweep:
        print("Running parameter sweep...")
        sweep = run_sweep(raw, config)
        path = safety.safe_write_json(sweep, SWEEP_PATH)
        print_sweep_table(sweep)
        print(f"\nwritten: {path}")
        return

    raw_enb = set(raw["enb"].dropna().astype(str).unique())
    modes = list(DEFAULT_MODES) if args.mode == "all" else [args.mode]

    log = TransformLog()
    print("Applying transforms 1-6...")
    prepared, meta = prepare(raw, config, log)

    all_stats: dict[str, Any] = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "seed": safety.SEED,
        "config": config,
        "time_bucket": meta,
        "rows_in": int(len(raw)),
        "modes": {},
    }

    RELEASES_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for mode in modes:
        print(f"Building '{mode}' release...")
        mode_log = TransformLog(list(log.entries))
        release, stats, _ = build_release(prepared, mode, config, mode_log)
        assert_release_safe(
            release, mode, int(config["k"]), raw_enb, config["area_mode"] == "enb_tokenised"
        )
        stats["rows_out"] = int(len(release))
        all_stats["modes"][mode] = stats
        written.append(safety.safe_write_df(release, RELEASES_DIR / f"{mode}.parquet"))
        
        # Write mode-suffixed reports
        transform_log = {
            "generated": all_stats["generated"],
            "config": config,
            "entries": mode_log.as_list(),
        }
        written.append(safety.safe_write_json(transform_log, Path(f"outputs/transform_log_{mode}.json")))
        
        mode_all_stats = all_stats.copy()
        mode_all_stats["modes"] = {mode: stats}
        written.append(safety.safe_write_json(mode_all_stats, Path(f"outputs/release_stats_{mode}.json")))
        
        written.append(
            safety.safe_write_text(
                render_transformations_doc(config, mode_log, mode_all_stats), Path(f"docs/transformations_{mode}.md")
            )
        )
        if mode == modes[-1]:
            log = mode_log

    written.append(update_fields_yaml(log, config))

    print("\n" + "=" * 68)
    print("ANONYMISATION COMPLETE")
    print("=" * 68)
    print(f"rows in: {all_stats['rows_in']:,} | time bucket: {meta['time_bucket_minutes']} min "
          f"| area_mode: {config['area_mode']} | k: {config['k']}")
    for mode, stats in all_stats["modes"].items():
        if "rows_suppressed" in stats:
            print(
                f"  {mode:<10} rows {stats['rows_out']:>9,}  "
                f"suppressed {stats['pct_suppressed']:>6}%  "
                f"escalated {stats['pct_escalated']:>6}%  "
                f"min subs/group {stats['min_subscribers_per_group']}"
            )
        else:
            dp = stats.get("dp", {})
            epsilon = dp.get("epsilon")
            print(
                f"  {mode:<10} cells {stats['cells_out']:>9,}  "
                f"suppressed {stats['pct_cells_suppressed']:>6}% "
                f"(primary {stats['cells_suppressed_primary']}, "
                f"secondary {stats['cells_suppressed_secondary']})  "
                f"min subs/cell {stats['min_subscribers_per_cell']}"
            )
            if epsilon:
                errors = stats.get("count_error", {})
                print(
                    f"  {'':<10} DP: Laplace eps={epsilon}, scale={dp['noise_scale']}; "
                    f"median rel. error n_subscribers "
                    f"{errors.get('median_rel_error_n_subscribers')}, "
                    f"n_rows {errors.get('median_rel_error_n_rows')}"
                )
    print("-" * 68)
    for path in written:
        print(f"written: {path}")


if __name__ == "__main__":
    main()
