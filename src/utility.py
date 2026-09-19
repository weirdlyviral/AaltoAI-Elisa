"""M4 - utility of the anonymised releases.

Answers one question: how much of the raw signal survives anonymisation?

The comparison is made fair by recomputing every statistic on raw data using
the *release's* grouping keys (same time floor, same rare-category folding) and
scoring only on cells the release actually published.

Read-only with respect to M2: this module imports from :mod:`src.anonymise` so
the bucketing and folding rules cannot silently diverge, but never modifies it.

Nothing cell-level is ever emitted - only error statistics, coverage shares,
correlations and overlaps.

Run with::

    python -m src.utility
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src import anonymise, safety

RELEASE_CONFIG_PATH = Path("config/release.yaml")
AGGREGATE_RELEASE_PATH = Path("outputs/releases/aggregate.parquet")
RECORD_RELEASE_PATH = Path("outputs/releases/record.parquet")
#: M3 may split release_stats; try the aggregate-specific file first.
RELEASE_STATS_CANDIDATES = (
    Path("outputs/release_stats_aggregate.json"),
    Path("outputs/release_stats.json"),
)
UTILITY_JSON_PATH = Path("outputs/utility_eval.json")
UTILITY_DOC_PATH = Path("docs/utility.md")

#: Metrics scored in U1. The first is the headline.
HEADLINE_METRIC = "tp_dl_avg"
U1_METRICS = (
    "tp_dl_avg",
    "tp_ul_avg",
    "cont_rtt_radio_avg",
    "http_response_time_avg",
    "http_sr_avg",
)
U1_STATISTICS = ("median", "p10", "p90")

#: Headline pass threshold.
WITHIN_TOLERANCE = 0.05
HEADLINE_TARGET = 0.90

U4_EPSILONS = (0.5, 1.0, 2.0)
BOTTOM_N = 10
#: U3 compares the bottom-decile cell SET rather than a fixed bottom-N list,
#: because winsorising ties a large block of cells at the clipped minimum.
BOTTOM_QUANTILE = 0.10

#: A metric is flagged when any of mean / p95 / p99 moves by at least this much.
DEGRADATION_FLAG_PCT = 5.0
#: Above this, the metric is not merely reshaped - it is no longer usable.
SEVERE_DEGRADATION_PCT = 25.0

CELL_KEYS = ["time_bucket", "province", "radio_access_type", "application_category"]


# --------------------------------------------------------------------------- #
# Statistics implemented on numpy (scipy is not an allowed dependency)
# --------------------------------------------------------------------------- #


def wasserstein_distance(left: np.ndarray, right: np.ndarray) -> float | None:
    """First Wasserstein distance between two empirical samples."""
    left = np.sort(np.asarray(left, dtype=float))
    right = np.sort(np.asarray(right, dtype=float))
    if left.size == 0 or right.size == 0:
        return None
    support = np.concatenate([left, right])
    support.sort(kind="mergesort")
    deltas = np.diff(support)
    if deltas.size == 0:
        return 0.0
    left_cdf = np.searchsorted(left, support[:-1], side="right") / left.size
    right_cdf = np.searchsorted(right, support[:-1], side="right") / right.size
    return float(np.sum(np.abs(left_cdf - right_cdf) * deltas))


def ks_statistic(left: np.ndarray, right: np.ndarray) -> float | None:
    """Two-sample Kolmogorov-Smirnov statistic (the D value only)."""
    left = np.sort(np.asarray(left, dtype=float))
    right = np.sort(np.asarray(right, dtype=float))
    if left.size == 0 or right.size == 0:
        return None
    support = np.concatenate([left, right])
    support.sort(kind="mergesort")
    left_cdf = np.searchsorted(left, support, side="right") / left.size
    right_cdf = np.searchsorted(right, support, side="right") / right.size
    return float(np.max(np.abs(left_cdf - right_cdf)))


def spearman(left: pd.Series, right: pd.Series) -> float | None:
    """Spearman rank correlation: Pearson on average-tied ranks."""
    frame = pd.DataFrame({"left": left, "right": right}).dropna()
    if len(frame) < 2:
        return None
    left_rank = frame["left"].rank(method="average").to_numpy(dtype=float)
    right_rank = frame["right"].rank(method="average").to_numpy(dtype=float)
    if np.std(left_rank) == 0 or np.std(right_rank) == 0:
        return None
    return float(np.corrcoef(left_rank, right_rank)[0, 1])


def jaccard(left: set, right: set) -> float | None:
    union = left | right
    return float(len(left & right) / len(union)) if union else None


def relative_error(released: np.ndarray, raw: np.ndarray) -> np.ndarray:
    """|released - raw| / |raw|, NaN where raw is zero or missing."""
    released = np.asarray(released, dtype=float)
    raw = np.asarray(raw, dtype=float)
    out = np.full(raw.shape, np.nan)
    usable = np.isfinite(raw) & np.isfinite(released) & (raw != 0)
    out[usable] = np.abs(released[usable] - raw[usable]) / np.abs(raw[usable])
    return out


def _describe_error(errors: np.ndarray) -> dict[str, Any]:
    clean = errors[np.isfinite(errors)]
    if clean.size == 0:
        return {"n": 0, "median": None, "p90": None, "mean": None, "pct_within_5pct": None}
    return {
        "n": int(clean.size),
        "median": safety.round_float(float(np.median(clean))),
        "p90": safety.round_float(float(np.percentile(clean, 90))),
        "mean": safety.round_float(float(np.mean(clean))),
        "pct_within_5pct": safety.round_float(
            100.0 * float(np.mean(clean <= WITHIN_TOLERANCE))
        ),
    }


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #


def load_release_config() -> dict[str, Any]:
    return yaml.safe_load(RELEASE_CONFIG_PATH.read_text(encoding="utf-8"))


def load_release_stats() -> tuple[dict[str, Any], str]:
    """Return (aggregate stats, which file it came from)."""
    for path in RELEASE_STATS_CANDIDATES:
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        stats = payload.get("modes", {}).get("aggregate", payload.get("aggregate", payload))
        return stats, str(path)
    raise FileNotFoundError(
        "No release stats found; expected one of: "
        + ", ".join(str(p) for p in RELEASE_STATS_CANDIDATES)
    )


def build_raw_comparison_frame(
    config: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Raw rows keyed exactly like the release: same floor, same OTHER folding.

    Identifiers are dropped immediately; only the internal subscriber key
    survives, and it never leaves this process.
    """
    log = anonymise.TransformLog()
    raw = safety.add_tac(safety.load_raw())
    rows_in = int(len(raw))
    subscribers_in = int(raw["msisdn"].nunique())

    work = anonymise.drop_identifiers(raw, log)
    bucket, native = anonymise.effective_bucket_minutes(
        work.assign(time_start=work["time_start"]), config.get("time_bucket_minutes")
    )
    work = anonymise.bucket_time(work, bucket, native, log)
    work = anonymise.fold_rare_categories(work, config, log)
    return work, {
        "rows_in": rows_in,
        "subscribers_in": subscribers_in,
        "time_bucket_minutes": bucket,
        "native_window_minutes": native,
    }


def raw_cell_statistics(raw_frame: pd.DataFrame) -> pd.DataFrame:
    """Recompute the release's cell statistics on raw values."""
    keys = [c for c in CELL_KEYS if c in raw_frame.columns]
    grouped = raw_frame.groupby(keys, observed=True, dropna=False)
    out = grouped.agg(
        n_rows=(anonymise.SUBSCRIBER, "size"),
        n_subscribers=(anonymise.SUBSCRIBER, "nunique"),
    )
    for column in anonymise.qoe_columns(raw_frame):
        out[f"{column}_p10"] = grouped[column].quantile(0.10)
        out[f"{column}_median"] = grouped[column].median()
        out[f"{column}_p90"] = grouped[column].quantile(0.90)
    for column in anonymise.volume_columns(raw_frame):
        out[f"{column}_total"] = grouped[column].sum()
    return out.reset_index()


def join_published_cells(
    release: pd.DataFrame, raw_cells: pd.DataFrame
) -> pd.DataFrame:
    """Inner join on the cell keys: scoring happens only on published cells."""
    keys = [c for c in CELL_KEYS if c in release.columns and c in raw_cells.columns]
    return release.merge(raw_cells, on=keys, how="inner", suffixes=("_rel", "_raw"))


# --------------------------------------------------------------------------- #
# U1 - headline accuracy
# --------------------------------------------------------------------------- #


def u1_accuracy(joined: pd.DataFrame) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for metric in U1_METRICS:
        per_statistic: dict[str, Any] = {}
        for statistic in U1_STATISTICS:
            column = f"{metric}_{statistic}"
            released, raw = f"{column}_rel", f"{column}_raw"
            if released not in joined.columns or raw not in joined.columns:
                continue
            per_statistic[statistic] = _describe_error(
                relative_error(joined[released].to_numpy(), joined[raw].to_numpy())
            )
        results[metric] = per_statistic

    headline = results.get(HEADLINE_METRIC, {}).get("median", {})
    share = headline.get("pct_within_5pct")
    return {
        "cells_scored": int(len(joined)),
        "tolerance_pct": WITHIN_TOLERANCE * 100,
        "target_pct": HEADLINE_TARGET * 100,
        "baseline_note": "Raw is the baseline: 100% of cells match raw by definition.",
        "headline_metric": HEADLINE_METRIC,
        "headline_statistic": "median",
        "headline_pct_within_5pct": share,
        "headline_pass": bool(share is not None and share >= HEADLINE_TARGET * 100),
        "per_metric": results,
    }


# --------------------------------------------------------------------------- #
# U2 - coverage
# --------------------------------------------------------------------------- #


def u2_coverage(raw_frame: pd.DataFrame, release: pd.DataFrame) -> dict[str, Any]:
    keys = [c for c in CELL_KEYS if c in release.columns and c in raw_frame.columns]
    published = release[keys].drop_duplicates().assign(_published=True)
    marked = raw_frame.merge(published, on=keys, how="left")
    # The merge leaves NaN where a row matched no published cell.
    marked["_published"] = marked["_published"].notna()

    total_rows = len(marked)
    total_subscribers = marked[anonymise.SUBSCRIBER].nunique()
    covered = marked.loc[marked["_published"]]

    def _split(column: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for value, group in marked.groupby(column, observed=True, dropna=False):
            kept = group.loc[group["_published"]]
            out[str(value)] = {
                "pct_rows_covered": safety.round_float(100.0 * len(kept) / len(group))
                if len(group)
                else None,
                "pct_subscribers_covered": safety.round_float(
                    100.0
                    * kept[anonymise.SUBSCRIBER].nunique()
                    / group[anonymise.SUBSCRIBER].nunique()
                )
                if group[anonymise.SUBSCRIBER].nunique()
                else None,
            }
        return out

    return {
        "pct_rows_covered": safety.round_float(100.0 * len(covered) / total_rows)
        if total_rows
        else None,
        "pct_subscribers_covered": safety.round_float(
            100.0 * covered[anonymise.SUBSCRIBER].nunique() / total_subscribers
        )
        if total_subscribers
        else None,
        "by_province": _split("province"),
        "by_radio_access_type": _split("radio_access_type"),
    }


# --------------------------------------------------------------------------- #
# U3 - the product question
# --------------------------------------------------------------------------- #


def _weighted_province_metric(frame: pd.DataFrame, column: str, weight: str) -> pd.Series:
    """Subscriber-weighted mean of a per-cell statistic, by province."""
    usable = frame[[*("province",), column, weight]].dropna()
    if usable.empty:
        return pd.Series(dtype=float)
    products = usable[column] * usable[weight]
    grouped = pd.DataFrame({"p": usable["province"], "num": products, "den": usable[weight]})
    summed = grouped.groupby("p", observed=True).sum()
    return (summed["num"] / summed["den"]).dropna()


def u3_product_question(
    joined: pd.DataFrame, winsorise_lower_clip: float | None = None
) -> dict[str, Any]:
    results: dict[str, Any] = {}

    for metric in ("tp_dl_avg", "http_sr_avg"):
        released = _weighted_province_metric(joined, f"{metric}_median_rel", "n_subscribers_rel")
        raw = _weighted_province_metric(joined, f"{metric}_median_raw", "n_subscribers_raw")
        aligned = pd.DataFrame({"rel": released, "raw": raw}).dropna()
        results[f"province_rank_spearman_{metric}"] = {
            "n_provinces": int(len(aligned)),
            "spearman": safety.round_float(spearman(aligned["rel"], aligned["raw"])),
        }

    def _bottom_overlap(frame: pd.DataFrame, label: str) -> dict[str, Any]:
        """Jaccard overlap of the bottom-decile cell SET, ties included.

        An earlier version took ``nsmallest(10)`` on each side. That is not
        safe here: winsorising clips the lower tail of every QoE metric, so a
        large block of cells shares the identical minimum value and
        ``nsmallest`` breaks the tie by row order. Both sides then return the
        same arbitrary rows and the overlap looks perfect without measuring
        anything. Taking every cell at or below the decile threshold makes the
        comparison tie-safe, and the tie counts below say how big the clipped
        block actually is.
        """
        keys = [c for c in CELL_KEYS if c in frame.columns]
        rel_values = frame["tp_dl_avg_median_rel"]
        raw_values = frame["tp_dl_avg_median_raw"]
        usable = frame[rel_values.notna() & raw_values.notna()]
        if usable.empty:
            return {
                "scope": label,
                "n_cells": int(len(frame)),
                "quantile": BOTTOM_QUANTILE,
                "n_bottom_released": None,
                "n_bottom_raw": None,
                "intersection": None,
                "union": None,
                "jaccard": None,
                "tie_at_min_released": None,
                "tie_at_min_raw": None,
            }

        def _bottom_set(column: str) -> tuple[set[tuple[str, ...]], float]:
            threshold = float(usable[column].quantile(BOTTOM_QUANTILE))
            selected = usable[usable[column] <= threshold][keys]
            return {tuple(map(str, row)) for row in selected.to_numpy()}, threshold

        rel_set, rel_threshold = _bottom_set("tp_dl_avg_median_rel")
        raw_set, raw_threshold = _bottom_set("tp_dl_avg_median_raw")

        rel_min = float(usable["tp_dl_avg_median_rel"].min())
        raw_min = float(usable["tp_dl_avg_median_raw"].min())

        # Counts and set overlaps only: the thresholds and minima themselves
        # are cell-level values and never leave this function.
        return {
            "scope": label,
            "n_cells": int(len(usable)),
            "quantile": BOTTOM_QUANTILE,
            "n_bottom_released": len(rel_set),
            "n_bottom_raw": len(raw_set),
            "intersection": len(rel_set & raw_set),
            "union": len(rel_set | raw_set),
            "jaccard": safety.round_float(jaccard(rel_set, raw_set)),
            "tie_at_min_released": int((usable["tp_dl_avg_median_rel"] == rel_min).sum()),
            "tie_at_min_raw": int((usable["tp_dl_avg_median_raw"] == raw_min).sum()),
            "_raw_min": raw_min,
        }

    results["bottom_cells_all"] = _bottom_overlap(joined, "all cells")
    five_g = joined[joined["radio_access_type"].astype(str).str.contains("5G", case=False, na=False)]
    if len(five_g):
        results["bottom_cells_5g"] = _bottom_overlap(five_g, "5G cells only")

    # Is the tie the winsorise floor, or a genuine feature of the data? The
    # raw minimum itself is a cell-level value, so it is compared here and
    # dropped: only the boolean leaves this function.
    for block in (results.get("bottom_cells_all"), results.get("bottom_cells_5g")):
        if not block:
            continue
        raw_min = block.pop("_raw_min", None)
        if winsorise_lower_clip is None or raw_min is None:
            block["tie_is_winsorise_floor"] = None
        else:
            block["tie_is_winsorise_floor"] = bool(
                abs(raw_min - winsorise_lower_clip)
                <= max(1e-9, abs(winsorise_lower_clip) * 0.02)
            )
    return results


# --------------------------------------------------------------------------- #
# U4 - count accuracy vs epsilon
# --------------------------------------------------------------------------- #


def u4_count_accuracy(
    joined: pd.DataFrame, dp_stats: dict[str, Any], stats_source: str
) -> dict[str, Any]:
    """Released error at the deployed epsilon, plus a re-noised privacy curve."""
    true_counts = joined["n_subscribers_raw"].to_numpy(dtype=float)
    released_counts = joined["n_subscribers_rel"].to_numpy(dtype=float)

    epsilon = dp_stats.get("epsilon")
    scale = dp_stats.get("noise_scale")
    sensitivity = dp_stats.get("assumed_sensitivity")
    if sensitivity is None and epsilon and scale:
        sensitivity = scale * epsilon

    curve: list[dict[str, Any]] = []
    for candidate in U4_EPSILONS:
        rng = np.random.default_rng(safety.SEED)
        candidate_scale = (sensitivity or 1) / candidate
        noisy = np.maximum(0, np.round(true_counts + rng.laplace(0.0, candidate_scale, true_counts.size)))
        errors = relative_error(noisy, true_counts)
        described = _describe_error(errors)
        curve.append(
            {
                "epsilon": candidate,
                "noise_scale": safety.round_float(candidate_scale),
                "median_rel_error": described["median"],
                "p90_rel_error": described["p90"],
            }
        )

    deployed = _describe_error(relative_error(released_counts, true_counts))
    return {
        "stats_source": stats_source,
        "deployed_epsilon": epsilon,
        "deployed_noise_scale": scale,
        "assumed_sensitivity": sensitivity,
        "deployed_median_rel_error": deployed["median"],
        "deployed_p90_rel_error": deployed["p90"],
        "note": (
            "Released counts are compared against true counts recomputed from raw "
            "on the published cells. The curve re-noises those true counts in "
            "memory; it never re-publishes anything."
        ),
        "curve": curve,
    }


# --------------------------------------------------------------------------- #
# U5 - record release distribution fidelity
# --------------------------------------------------------------------------- #


def u5_distribution_fidelity(
    raw_frame: pd.DataFrame, record: pd.DataFrame
) -> dict[str, Any]:
    metrics = [
        column
        for column in (*anonymise.qoe_columns(raw_frame), *anonymise.volume_columns(raw_frame))
        if column in record.columns
    ]
    results: dict[str, Any] = {}
    for metric in metrics:
        raw_values = pd.to_numeric(raw_frame[metric], errors="coerce").dropna().to_numpy()
        rel_values = pd.to_numeric(record[metric], errors="coerce").dropna().to_numpy()
        if raw_values.size == 0 or rel_values.size == 0:
            continue

        def _pct_change(new: float, old: float) -> float | None:
            return safety.round_float(100.0 * (new - old) / old) if old else None

        changes = {
            "mean": _pct_change(float(np.mean(rel_values)), float(np.mean(raw_values))),
            "p50": _pct_change(float(np.median(rel_values)), float(np.median(raw_values))),
            "p95": _pct_change(
                float(np.percentile(rel_values, 95)), float(np.percentile(raw_values, 95))
            ),
            "p99": _pct_change(
                float(np.percentile(rel_values, 99)), float(np.percentile(raw_values, 99))
            ),
        }

        # p95 alone cannot see a cap applied at p99, and on a skewed metric the
        # mean is carried almost entirely by the tail that top-coding removes.
        # Flagging on mean/p95/p99 together is what makes the damage visible.
        flags = [
            name
            for name in ("mean", "p95", "p99")
            if changes[name] is not None and abs(changes[name]) >= DEGRADATION_FLAG_PCT
        ]
        mean_change = changes["mean"]
        results[metric] = {
            "wasserstein": safety.round_float(wasserstein_distance(raw_values, rel_values)),
            "ks_statistic": safety.round_float(ks_statistic(raw_values, rel_values)),
            "pct_change_mean": changes["mean"],
            "pct_change_p50": changes["p50"],
            "pct_change_p95": changes["p95"],
            "pct_change_p99": changes["p99"],
            "share_zero_raw": safety.round_float(float(np.mean(raw_values == 0))),
            "share_zero_released": safety.round_float(float(np.mean(rel_values == 0))),
            "flags": flags,
            "tail_flagged": bool(flags),
            "severely_degraded": bool(
                mean_change is not None and abs(mean_change) >= SEVERE_DEGRADATION_PCT
            ),
        }

    flagged = sorted(m for m, r in results.items() if r["tail_flagged"])
    severe = sorted(m for m, r in results.items() if r["severely_degraded"])
    return {
        "metrics": results,
        "tail_flagged_metrics": flagged,
        "severely_degraded_metrics": severe,
        "flag_threshold_pct": DEGRADATION_FLAG_PCT,
        "severe_threshold_pct": SEVERE_DEGRADATION_PCT,
        "note": (
            "tail_flagged marks metrics where the mean, p95 or p99 moved by at "
            f"least {DEGRADATION_FLAG_PCT}%. severely_degraded marks metrics whose "
            f"mean moved by at least {SEVERE_DEGRADATION_PCT}%: on a sparse or "
            "heavily skewed column, top-coding at a quantile that sits at or near "
            "zero removes essentially all of the signal."
        ),
    }


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #


def _fmt(value: Any) -> str:
    return "n/a" if value is None else str(value)


def render_utility_doc(report: dict[str, Any]) -> str:
    u1, u2, u3, u4, u5 = (report["U1"], report["U2"], report["U3"], report["U4"], report["U5"])
    verdict = "**PASS**" if u1["headline_pass"] else "**FAIL**"

    lines = [
        "# Utility evaluation",
        "",
        "Generated by `python -m src.utility`. Do not edit by hand.",
        "",
        "## 1. Headline",
        "",
        f"Median download throughput is within {u1['tolerance_pct']:.0f}% of raw for "
        f"**{_fmt(u1['headline_pct_within_5pct'])}%** of published cells "
        f"(target >= {u1['target_pct']:.0f}%). {verdict}",
        "",
        f"Scored on {u1['cells_scored']:,} published cells. {u1['baseline_note']}",
        "",
        "## 2. U1 - accuracy per metric",
        "",
        "| metric | statistic | cells | median rel. error | p90 rel. error | % within 5% |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for metric, statistics in u1["per_metric"].items():
        for statistic, values in statistics.items():
            lines.append(
                f"| {metric} | {statistic} | {values['n']:,} | {_fmt(values['median'])} | "
                f"{_fmt(values['p90'])} | {_fmt(values['pct_within_5pct'])} |"
            )

    lines += [
        "",
        "## 3. U2 - coverage (the cost of suppression)",
        "",
        f"Published cells contain **{_fmt(u2['pct_rows_covered'])}%** of raw rows and "
        f"**{_fmt(u2['pct_subscribers_covered'])}%** of raw subscribers.",
        "",
        "| radio access type | % rows covered | % subscribers covered |",
        "| --- | --- | --- |",
    ]
    for value, cover in sorted(u2["by_radio_access_type"].items()):
        lines.append(
            f"| {value} | {_fmt(cover['pct_rows_covered'])} | {_fmt(cover['pct_subscribers_covered'])} |"
        )
    lines += [
        "",
        "| province | % rows covered | % subscribers covered |",
        "| --- | --- | --- |",
    ]
    for value, cover in sorted(u2["by_province"].items(), key=lambda kv: (kv[1]["pct_rows_covered"] or 0)):
        lines.append(
            f"| {value} | {_fmt(cover['pct_rows_covered'])} | {_fmt(cover['pct_subscribers_covered'])} |"
        )

    lines += [
        "",
        "## 4. U3 - \"where is service quality worst?\"",
        "",
        "| question | value |",
        "| --- | --- |",
    ]
    for metric in ("tp_dl_avg", "http_sr_avg"):
        block = u3.get(f"province_rank_spearman_{metric}", {})
        lines.append(
            f"| Spearman rank correlation of provinces by median {metric} "
            f"({block.get('n_provinces', 0)} provinces) | {_fmt(block.get('spearman'))} |"
        )
    for key in ("bottom_cells_all", "bottom_cells_5g"):
        block = u3.get(key)
        if block:
            pct = int(round(block.get("quantile", 0) * 100))
            lines.append(
                f"| Bottom-{pct}% worst cells (ties included), {block['scope']} "
                f"(of {block['n_cells']:,}) | Jaccard {_fmt(block['jaccard'])}; "
                f"{_fmt(block['intersection'])} shared of {_fmt(block['union'])} in the union "
                f"({_fmt(block['n_bottom_raw'])} raw, {_fmt(block['n_bottom_released'])} released) |"
            )

    all_cells = u3.get("bottom_cells_all", {})
    if all_cells.get("tie_at_min_raw"):
        verdict = all_cells.get("tie_is_winsorise_floor")
        lines += [
            "",
            f"**Ties at the bottom.** {all_cells['tie_at_min_raw']:,} cells share the minimum "
            f"raw value and {all_cells.get('tie_at_min_released', 0):,} share the minimum "
            f"released value. Compared against the lower winsorise clip on "
            f"`{HEADLINE_METRIC}`, that tie "
            + (
                "IS the clip: winsorising flattens the bottom of this distribution, so any "
                "\"worst N cells\" ranking taken from below the clip is arbitrary. That is why "
                "U3 compares the bottom-decile SET with ties included rather than a top-N list."
                if verdict
                else "is NOT the clip - it is a feature of the data itself."
                if verdict is False
                else "could not be compared with the clip."
            ),
        ]

    lines += [
        "",
        "## 5. U4 - count accuracy vs epsilon",
        "",
        f"Deployed: epsilon {_fmt(u4['deployed_epsilon'])}, scale "
        f"{_fmt(u4['deployed_noise_scale'])} (from `{u4['stats_source']}`); "
        f"median relative error {_fmt(u4['deployed_median_rel_error'])}, "
        f"p90 {_fmt(u4['deployed_p90_rel_error'])}.",
        "",
        "| epsilon | noise scale | median rel. error | p90 rel. error |",
        "| --- | --- | --- | --- |",
    ]
    for row in u4["curve"]:
        lines.append(
            f"| {row['epsilon']} | {_fmt(row['noise_scale'])} | "
            f"{_fmt(row['median_rel_error'])} | {_fmt(row['p90_rel_error'])} |"
        )

    lines += [
        "",
        "## 6. U5 - record release distribution fidelity",
        "",
        "| metric | Wasserstein | KS | % change mean | % change p50 | % change p95 | % change p99 | share zero raw -> released | flags |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for metric, values in u5["metrics"].items():
        lines.append(
            f"| {metric} | {_fmt(values['wasserstein'])} | {_fmt(values['ks_statistic'])} | "
            f"{_fmt(values['pct_change_mean'])} | {_fmt(values['pct_change_p50'])} | "
            f"{_fmt(values['pct_change_p95'])} | {_fmt(values['pct_change_p99'])} | "
            f"{_fmt(values['share_zero_raw'])} -> {_fmt(values['share_zero_released'])} | "
            f"{', '.join(values['flags']) or '-'} |"
        )

    severe = u5.get("severely_degraded_metrics", [])
    if severe:
        lines += [
            "",
            f"**{len(severe)} metric(s) are severely degraded** (mean moved by at least "
            f"{u5['severe_threshold_pct']}%): " + ", ".join(f"`{m}`" for m in severe) + ".",
            "",
            "These are sparse or heavily skewed columns. Top-coding at the 0.99",
            "quantile removes the tail that carries almost all of their mass, and where",
            "that quantile is itself at or near zero the column is flattened entirely.",
            "Medians survive, so U1 looks healthy; any question about totals or averages",
            "on these metrics does not. This is a property of the release parameters,",
            "not of the measurement.",
        ]

    lines += [
        "",
        "## 7. Trade-off: what the aggregate release cannot answer",
        "",
        "- **Individual journeys.** There is no subscriber key, so no question of the",
        "  form \"what did this customer experience\" can be asked at all.",
        "- **Micro-level fault diagnosis.** Location is generalised to province, so a",
        "  single bad cell cannot be isolated from the aggregate release. The record",
        "  release keeps a tokenised area, which is the reason to publish it alongside.",
        "- **Rare cells.** Any (bucket, province, technology, application) combination",
        "  below the subscriber threshold is suppressed outright, and the smallest",
        "  survivor in an affected slice goes with it.",
        "",
        f"Coverage is uneven by design: see the province table above, where the least",
        f"covered province retains "
        f"{_fmt(min((c['pct_rows_covered'] or 0) for c in u2['by_province'].values()))}% of its rows",
        f"against {_fmt(max((c['pct_rows_covered'] or 0) for c in u2['by_province'].values()))}% for the best.",
        "Threshold methods always cost the thin strata the most, so the regions with",
        "the fewest subscribers are the ones a product team can say least about.",
        "",
        "## 8. Assumptions and limitations",
        "",
        "- The extract is a single hour of fabricated data. Utility on real,",
        "  longitudinal data may differ substantially.",
        "- Raw is the baseline by definition: it scores 100%, so every number here is",
        "  a loss relative to something that could never be published.",
        "- Statistics are compared only on published cells. Suppressed cells are a",
        "  coverage cost (U2), not an accuracy cost, and the two must be read together.",
        "- Wasserstein and KS are computed on the pooled distribution per metric, not",
        "  per cell, so they describe shape rather than local error.",
        "",
    ]
    return "\n".join(lines)


def print_summary(report: dict[str, Any]) -> None:
    u1, u2, u4 = report["U1"], report["U2"], report["U4"]
    print("=" * 72)
    print("UTILITY EVALUATION")
    print("=" * 72)
    verdict = "PASS" if u1["headline_pass"] else "FAIL"
    print(
        f"HEADLINE: median {u1['headline_metric']} within "
        f"{u1['tolerance_pct']:.0f}% of raw for {u1['headline_pct_within_5pct']}% "
        f"of {u1['cells_scored']:,} published cells "
        f"(target >= {u1['target_pct']:.0f}%) -> {verdict}"
    )
    print("-" * 72)
    print(f"{'metric':<26} {'median err':>11} {'p90 err':>10} {'% within 5%':>12}")
    for metric, statistics in u1["per_metric"].items():
        values = statistics.get("median", {})
        print(
            f"{metric:<26} {_fmt(values.get('median')):>11} "
            f"{_fmt(values.get('p90')):>10} {_fmt(values.get('pct_within_5pct')):>12}"
        )
    print("-" * 72)
    print(
        f"coverage: {u2['pct_rows_covered']}% of raw rows, "
        f"{u2['pct_subscribers_covered']}% of raw subscribers"
    )
    print(
        f"counts at deployed epsilon {u4['deployed_epsilon']}: "
        f"median rel. error {u4['deployed_median_rel_error']}, "
        f"p90 {u4['deployed_p90_rel_error']}"
    )
    u5 = report["U5"]
    print(
        f"distribution flags: {len(u5['tail_flagged_metrics'])} metric(s) moved >= "
        f"{u5['flag_threshold_pct']}% on mean/p95/p99"
    )
    severe = u5.get("severely_degraded_metrics", [])
    if severe:
        print(f"SEVERELY DEGRADED ({len(severe)}): {', '.join(severe)}")
    print("=" * 72)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


@safety.safe_main
def main(argv: list[str] | None = None) -> None:
    for path in (AGGREGATE_RELEASE_PATH, RECORD_RELEASE_PATH):
        if not path.exists():
            raise FileNotFoundError(f"{path} not found - run python -m src.anonymise first.")

    config = load_release_config()
    dp_stats_block, stats_source = load_release_stats()
    dp_stats = dp_stats_block.get("dp", {})

    print("Rebuilding the raw comparison frame...")
    raw_frame, meta = build_raw_comparison_frame(config)

    print("Recomputing cell statistics on raw...")
    raw_cells = raw_cell_statistics(raw_frame)

    print("Loading releases...")
    aggregate = pd.read_parquet(AGGREGATE_RELEASE_PATH)
    record = pd.read_parquet(RECORD_RELEASE_PATH)
    joined = join_published_cells(aggregate, raw_cells)

    # The lower winsorise clip applied to the headline QoE metric, so U3 can
    # say whether the tie at the bottom of the distribution is that clip.
    winsorise_bounds = config.get("numeric_winsorise") or [None, None]
    winsorise_clip = (
        float(raw_frame[HEADLINE_METRIC].quantile(winsorise_bounds[0]))
        if winsorise_bounds[0] is not None and HEADLINE_METRIC in raw_frame.columns
        else None
    )

    print("Scoring U1-U5...")
    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "seed": safety.SEED,
        "inputs": {
            "aggregate_release": str(AGGREGATE_RELEASE_PATH),
            "record_release": str(RECORD_RELEASE_PATH),
            "release_stats": stats_source,
            "config": config,
        },
        "raw_baseline": meta,
        "U1": u1_accuracy(joined),
        "U2": u2_coverage(raw_frame, aggregate),
        "U3": u3_product_question(joined, winsorise_lower_clip=winsorise_clip),
        "U4": u4_count_accuracy(joined, dp_stats, stats_source),
        "U5": u5_distribution_fidelity(raw_frame, record),
    }

    json_path = safety.safe_write_json(report, UTILITY_JSON_PATH)
    doc_path = safety.safe_write_text(render_utility_doc(report), UTILITY_DOC_PATH)

    print_summary(report)
    print(f"written: {json_path}")
    print(f"written: {doc_path}")


if __name__ == "__main__":
    main()
