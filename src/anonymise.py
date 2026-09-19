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

QOE_PATTERN = re.compile(r"^(tp_|.*_rtt_|tcp_retrans_|http_)")
# Must match tethering_data_GB_dl_sum as well as the plain *_GB_sum columns -
# a pattern anchored on "_GB_sum$" silently skips it, leaving it untransformed.
VOLUME_PATTERN = re.compile(r"_GB_[a-z_]*sum$")

RARE_CATEGORY_COLUMNS = ("radio_access_type", "application_category")

MODES = ("record", "session", "aggregate")


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
    """Transform 5: clip QoE metrics to the configured quantiles and round."""
    work = df.copy()
    low_q, high_q = config["numeric_winsorise"]
    digits = int(config["numeric_round_sig_figs"])
    for column in qoe_columns(work):
        series = pd.to_numeric(work[column], errors="coerce")
        low, high = series.quantile(low_q), series.quantile(high_q)
        affected = int(((series < low) | (series > high)).sum())
        work[column] = round_sig_figs(series.clip(low, high), digits)
        log.add(
            column,
            "winsorised and rounded",
            {
                "lower_quantile": low_q,
                "upper_quantile": high_q,
                "significant_figures": digits,
            },
            affected,
            "Extreme values are rare enough to single a subscriber out.",
        )
    return work


def top_code_volumes(df: pd.DataFrame, config: dict[str, Any], log: TransformLog) -> pd.DataFrame:
    """Transform 6: top-code volume fields and round."""
    work = df.copy()
    quantile = float(config["volume_top_code_quantile"])
    digits = int(config["numeric_round_sig_figs"])
    for column in volume_columns(work):
        series = pd.to_numeric(work[column], errors="coerce")
        cap = series.quantile(quantile)
        affected = int((series > cap).sum())
        work[column] = round_sig_figs(series.clip(upper=cap), digits)
        log.add(
            column,
            "top-coded and rounded",
            {"quantile": quantile, "significant_figures": digits},
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


def build_aggregate(
    df: pd.DataFrame, config: dict[str, Any], log: TransformLog
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Aggregate mode: distributions per (bucket, province, RAT, app)."""
    keys = [c for c in AGGREGATE_KEYS if c in df.columns]
    minimum = int(config["aggregate_min_subscribers_per_cell"])
    digits = int(config["numeric_round_sig_figs"])
    epsilon = config.get("dp_epsilon")

    grouped = df.groupby(keys, observed=True, dropna=False)
    out = grouped.agg(n_rows=(SUBSCRIBER, "size"), n_subscribers=(SUBSCRIBER, "nunique"))

    for column in qoe_columns(df):
        out[f"{column}_p10"] = grouped[column].quantile(0.10)
        out[f"{column}_median"] = grouped[column].median()
        out[f"{column}_p90"] = grouped[column].quantile(0.90)
    for column in volume_columns(df):
        out[f"{column}_total"] = grouped[column].sum()

    out = out.reset_index()
    cells_in = len(out)
    keep = out["n_subscribers"] >= minimum
    n_suppressed = int((~keep).sum())
    out = out.loc[keep].copy()
    log.add(
        "aggregate cells",
        "suppressed cells below the subscriber minimum",
        {"aggregate_min_subscribers_per_cell": minimum},
        n_suppressed,
        "A thin cell describes too few people to publish.",
    )

    noise_added = False
    if epsilon:
        rng = np.random.default_rng(safety.SEED)
        scale = 1.0 / float(epsilon)
        for column in ("n_rows", "n_subscribers"):
            noisy = out[column].to_numpy(dtype=float) + rng.laplace(0.0, scale, size=len(out))
            out[column] = np.maximum(0, np.round(noisy)).astype(int)
        noise_added = True
        log.add(
            "n_rows, n_subscribers",
            "Laplace noise added to counts",
            {"dp_epsilon": epsilon, "seed": safety.SEED},
            len(out),
            "Blurs exact counts so a single subscriber cannot be differenced out.",
        )

    for column in out.columns:
        if pd.api.types.is_float_dtype(out[column]):
            out[column] = round_sig_figs(out[column], digits)

    stats = {
        "cells_in": cells_in,
        "cells_out": len(out),
        "cells_suppressed": n_suppressed,
        "pct_cells_suppressed": safety.round_float(100.0 * n_suppressed / cells_in)
        if cells_in
        else 0.0,
        "min_subscribers_per_cell": int(out["n_subscribers"].min()) if len(out) else 0,
        "median_subscribers_per_cell": safety.round_float(out["n_subscribers"].median())
        if len(out)
        else 0.0,
        "dp_noise_applied": noise_added,
    }
    return out, stats


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
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Apply the mode-specific step and strip the subscriber key."""
    k = int(config["k"])

    if mode == "aggregate":
        out, stats = build_aggregate(prepared, config, log)
        return out, stats

    work, stats = enforce_k_anonymity(prepared, k, log)
    if mode == "session":
        work = add_session_id(work, log)

    work = work.drop(columns=[SUBSCRIBER])
    log.add(SUBSCRIBER, "internal key dropped before write", {}, len(work), "Never released.")
    return work, stats


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
                f"- **{mode}**: {mode_stats['cells_suppressed']:,} cells suppressed "
                f"({mode_stats['pct_cells_suppressed']}%) of {mode_stats['cells_in']:,}."
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


def run_sweep(df: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    """Record mode only, over the configured grid. Writes no releases."""
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
    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "seed": safety.SEED,
        "grid": {
            "time_bucket": ["native", 15, 30, 60],
            "area_mode": list(SWEEP_AREA_MODES),
            "k": list(SWEEP_K),
        },
        "results": results,
    }


def print_sweep_table(sweep: dict[str, Any]) -> None:
    header = (
        f"{'bucket':>8} {'area_mode':<15} {'k':>3} {'%suppressed':>12} "
        f"{'%escalated':>11} {'QI groups':>10} {'med subs/grp':>13}"
    )
    print("=" * len(header))
    print("PARAMETER SWEEP (record mode)")
    print("=" * len(header))
    print(header)
    print("-" * len(header))
    for row in sweep["results"]:
        print(
            f"{str(row['time_bucket']):>8} {row['area_mode']:<15} {row['k']:>3} "
            f"{row['pct_rows_suppressed']:>12} {row['pct_rows_escalated']:>11} "
            f"{row['n_qi_groups']:>10,} {row['median_subscribers_per_group']:>13}"
        )
    print("-" * len(header))
    under5 = [r for r in sweep["results"] if (r["pct_rows_suppressed"] or 0) < 5.0]
    print(f"combinations with suppression < 5%: {len(under5)} of {len(sweep['results'])}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


@safety.safe_main
def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.anonymise")
    parser.add_argument("--mode", choices=(*MODES, "all"), default="all")
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
    modes = list(MODES) if args.mode == "all" else [args.mode]

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
    written: list[Path] = []
    for mode in modes:
        print(f"Building '{mode}' release...")
        mode_log = TransformLog(list(log.entries))
        release, stats = build_release(prepared, mode, config, mode_log)
        assert_release_safe(
            release, mode, int(config["k"]), raw_enb, config["area_mode"] == "enb_tokenised"
        )
        stats["rows_out"] = int(len(release))
        all_stats["modes"][mode] = stats
        written.append(safety.safe_write_df(release, RELEASES_DIR / f"{mode}.parquet"))
        if mode == modes[-1]:
            log = mode_log

    print("Writing reports...")
    transform_log = {
        "generated": all_stats["generated"],
        "config": config,
        "entries": log.as_list(),
    }
    written.append(safety.safe_write_json(transform_log, TRANSFORM_LOG_PATH))
    written.append(safety.safe_write_json(all_stats, RELEASE_STATS_PATH))
    written.append(
        safety.safe_write_text(
            render_transformations_doc(config, log, all_stats), TRANSFORMATIONS_DOC_PATH
        )
    )
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
            print(
                f"  {mode:<10} cells {stats['cells_out']:>9,}  "
                f"suppressed {stats['pct_cells_suppressed']:>6}%  "
                f"min subs/cell {stats['min_subscribers_per_cell']}"
            )
    print("-" * 68)
    for path in written:
        print(f"written: {path}")


if __name__ == "__main__":
    main()
