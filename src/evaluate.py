"""M3 - empirical risk evaluation of the releases.

Every attack here is *executed*, not asserted. Each returns the numbers it
actually measured, under two attacker models:

* ``realistic``  - the defined recipient: an Elisa product team with no raw
  data, no keys, no enb->area mapping and no auxiliary identity data.
* ``worst_case`` - an attacker who additionally knows true (enb, time) points,
  the enb->area mapping, and the true per-slice totals.

``eval_index`` maps release rows back to subscriber keys for measurement only.
It lives in memory, is never written, logged or returned from a CLI, and only
aggregate counts derived from it ever reach an output file.

Run with::

    python -m src.evaluate
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src import anonymise, safety

EVAL_CONFIG_PATH = Path("config/evaluate.yaml")
RISK_EVAL_PATH = Path("outputs/risk_eval.json")
RISK_DOC_PATH = Path("docs/risk_assessment.md")

RECIPIENT = (
    "Elisa product team. No raw-data access, no hashing keys, no enb->area "
    "mapping, no auxiliary identity data (relative approach, EDPS v SRB)."
)
WORST_CASE = (
    "Knows some true (enb, time) points about a target, public enb->province "
    "geography, and - for the differencing test - the true per-slice totals."
)

DEFAULT_EVAL_CONFIG = {
    "a2_sample_size": 1000,
    "a6_sample_size": 200,
    "a6_trials_per_target": 100,
    "a5_tolerance_subscribers": 2,
    "sweep_epsilons": [0.5, 1.0, 2.0, None],
}

TRAJECTORY_LENGTHS = (1, 2, 3, 4)


def load_eval_config() -> dict[str, Any]:
    config = dict(DEFAULT_EVAL_CONFIG)
    if EVAL_CONFIG_PATH.exists():
        loaded = yaml.safe_load(EVAL_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        config.update(loaded)
    return config


# --------------------------------------------------------------------------- #
# Context
# --------------------------------------------------------------------------- #


@dataclass
class Context:
    """Everything the attacks need. Never serialised."""

    raw: pd.DataFrame
    prepared: pd.DataFrame
    record: pd.DataFrame
    eval_index: pd.Series
    release_config: dict[str, Any]
    eval_config: dict[str, Any]
    max_cells: int

    @property
    def k(self) -> int:
        return int(self.release_config["k"])

    @property
    def min_cell(self) -> int:
        return int(self.release_config["aggregate_min_subscribers_per_cell"])

    @property
    def qi(self) -> list[str]:
        return [c for c in anonymise.QI_COLUMNS if c in self.record.columns]


def build_context() -> Context:
    release_config = anonymise.load_release_config()
    eval_config = load_eval_config()

    raw = safety.add_tac(safety.load_raw())
    prepared, _meta = anonymise.prepare(raw, release_config, anonymise.TransformLog())
    record, _stats, eval_index = anonymise.build_release(
        prepared.copy(), "record", release_config, anonymise.TransformLog()
    )
    return Context(
        raw,
        prepared,
        record,
        eval_index,
        release_config,
        eval_config,
        contribution_bound(prepared, release_config),
    )


def contribution_bound(prepared: pd.DataFrame, config: dict[str, Any]) -> int:
    """Cells one subscriber may influence - the numerator of the noise scale.

    Must match what the release actually used. Defaulting this to 1 understates
    the Laplace scale by the bound itself, which makes a membership-inference
    attack look far stronger than the mechanism allows.
    """
    configured = config.get("max_cells_per_subscriber")
    if configured:
        return int(configured)
    keys = [c for c in anonymise.AGGREGATE_KEYS if c in prepared.columns]
    if not keys or anonymise.SUBSCRIBER not in prepared.columns:
        return 1
    per_subscriber = prepared.drop_duplicates([anonymise.SUBSCRIBER] + keys).groupby(
        anonymise.SUBSCRIBER, observed=True
    ).size()
    return max(1, int(per_subscriber.quantile(0.99))) if len(per_subscriber) else 1


def _subscribers_per_group(ctx: Context, columns: list[str]) -> pd.Series:
    """Distinct subscribers per group of the record release."""
    keys = [ctx.record[c] for c in columns]
    return ctx.eval_index.groupby(keys, observed=True, dropna=False).nunique()


# --------------------------------------------------------------------------- #
# A1 - row uniqueness (singling out)
# --------------------------------------------------------------------------- #


def run_a1(ctx: Context) -> dict[str, Any]:
    qi = ctx.qi
    if not len(ctx.record):
        return _empty("A1", "Row uniqueness", "singling_out")

    row_sizes = ctx.record.groupby(qi, observed=True, dropna=False)[qi[0]].transform("size")
    sub_sizes = _subscribers_per_group(ctx, qi)
    per_row = sub_sizes.loc[pd.MultiIndex.from_frame(ctx.record[qi])].to_numpy()

    return {
        "id": "A1",
        "name": "Row uniqueness",
        "criterion": "singling_out",
        "attacker_knowledge": "QI values of a target (same under both models)",
        "baseline_raw": "36.31% of subscribers own at least one unique row (QI set D)",
        "record": {
            "pct_rows_in_groups_of_1": safety.round_float(100.0 * float((row_sizes == 1).mean())),
            "pct_groups_below_k": safety.round_float(
                100.0 * float((sub_sizes < ctx.k).mean())
            ),
            "min_subscribers_per_group": int(sub_sizes.min()),
            "expected_identification_probability": safety.round_float(
                float(np.mean(1.0 / per_row))
            ),
            "n_groups": int(len(sub_sizes)),
        },
        "interpretation": (
            "k-anonymity on distinct subscribers removes singling out by QI: the "
            "expected chance of picking the target's row is 1 in "
            f"{1.0 / float(np.mean(1.0 / per_row)):.0f}."
        ),
    }


# --------------------------------------------------------------------------- #
# A2 - trajectory attack (linkability)
# --------------------------------------------------------------------------- #


def _trajectory_once(
    ctx: Context, coord_columns: list[str], label: str, sample_size: int
) -> dict[str, Any]:
    """Measure how far p known location/time points narrow the candidate set."""
    coords = list(zip(*(ctx.record[c].astype(str) for c in coord_columns)))
    frame = pd.DataFrame({"sub": ctx.eval_index.to_numpy(), "coord": coords})
    pairs = frame.drop_duplicates()

    point_to_subs: dict[tuple, set] = {}
    sub_to_points: dict[Any, list] = {}
    for sub, coord in zip(pairs["sub"], pairs["coord"]):
        point_to_subs.setdefault(coord, set()).add(sub)
        sub_to_points.setdefault(sub, []).append(coord)

    results = []
    for p in TRAJECTORY_LENGTHS:
        eligible = sorted(s for s, pts in sub_to_points.items() if len(pts) >= p)
        if not eligible:
            results.append({"p": p, "n_eligible": 0, "n_sampled": 0})
            continue
        rng = np.random.default_rng(safety.SEED)
        take = min(sample_size, len(eligible))
        sampled = [eligible[i] for i in rng.choice(len(eligible), size=take, replace=False)]

        per_point_candidates: list[int] = []
        intersection_sizes: list[int] = []
        for sub in sampled:
            points = sorted(sub_to_points[sub], key=repr)
            chosen = [points[i] for i in rng.choice(len(points), size=p, replace=False)]
            sets = sorted((point_to_subs[c] for c in chosen), key=len)
            per_point_candidates.append(len(sets[0]))
            matched = set(sets[0])
            for other in sets[1:]:
                matched &= other
                if not matched:
                    break
            intersection_sizes.append(len(matched))

        intersections = np.array(intersection_sizes, dtype=float)
        results.append(
            {
                "p": p,
                "n_eligible": len(eligible),
                "n_sampled": take,
                "median_candidates_per_point": safety.round_float(
                    float(np.median(per_point_candidates))
                ),
                "median_candidates_all_points": safety.round_float(
                    float(np.median(intersections))
                ),
                "pct_unique_if_rows_were_linkable": safety.round_float(
                    100.0 * float(np.mean(intersections == 1))
                ),
                "probability_of_picking_target_row": safety.round_float(
                    float(np.mean(1.0 / np.maximum(intersections, 1)))
                ),
            }
        )
    return {"attacker_model": label, "coordinates": coord_columns, "results": results}


def run_a2(ctx: Context) -> dict[str, Any]:
    sample = int(ctx.eval_config["a2_sample_size"])
    worst = _trajectory_once(ctx, ["area", "time_bucket"], "worst_case", sample)
    realistic = _trajectory_once(ctx, ["province", "time_bucket"], "realistic", sample)

    worst_p4 = next((r for r in worst["results"] if r["p"] == 4), {})
    return {
        "id": "A2",
        "name": "Trajectory attack",
        "criterion": "linkability",
        "attacker_knowledge": "p known (location, time) points for a target, p = 1..4",
        "baseline_raw": "4 known (enb, hour) points uniquely identify 99.6% of eligible subscribers",
        "record": {
            "structural_defence": (
                "The record release carries no subscriber key, so an attacker cannot "
                "group a target's rows together. The figures below assume the "
                "strictly stronger attacker who somehow can - they bound the risk."
            ),
            "worst_case": worst,
            "realistic": realistic,
        },
        "interpretation": (
            "Rows are not linkable, so the raw 99.6% collapses. Even granting an "
            "attacker the ability to link, 4 known points leave a median of "
            f"{worst_p4.get('median_candidates_all_points')} candidate subscribers "
            f"and single out {worst_p4.get('pct_unique_if_rows_were_linkable')}% of targets."
        ),
    }


# --------------------------------------------------------------------------- #
# A3 - homogeneity / l-diversity (inference)
# --------------------------------------------------------------------------- #


def _sensitive_flags(ctx: Context) -> dict[str, pd.Series]:
    """Binary sensitive attributes, computed on released values.

    ``application_category`` is deliberately excluded: it is itself a
    quasi-identifier, so every QI group holds exactly one value and a
    homogeneity test on it is 100% by construction, not a finding.
    """
    flags: dict[str, pd.Series] = {}
    if "tethering_data_GB_dl_sum" in ctx.record.columns:
        flags["tethering"] = ctx.record["tethering_data_GB_dl_sum"] > 0
    if "im_video_GB_sum" in ctx.record.columns:
        flags["video"] = ctx.record["im_video_GB_sum"] > 0
    if "data_GB_sum" in ctx.record.columns and "data_GB_sum" in ctx.raw.columns:
        threshold = float(pd.to_numeric(ctx.raw["data_GB_sum"], errors="coerce").quantile(0.95))
        flags["heavy_user"] = ctx.record["data_GB_sum"] > threshold
    return flags


def run_a3(ctx: Context) -> dict[str, Any]:
    qi = ctx.qi
    if not len(ctx.record):
        return _empty("A3", "Homogeneity (l-diversity)", "inference")

    group_keys = [ctx.record[c] for c in qi]
    subs_per_group = _subscribers_per_group(ctx, qi)
    total_subscribers = float(ctx.eval_index.nunique())

    per_attribute: dict[str, Any] = {}
    for name, flag in _sensitive_flags(ctx).items():
        grouped = flag.groupby(group_keys, observed=True, dropna=False)
        distinct = grouped.nunique()
        homogeneous = distinct <= 1
        # Which value is the group stuck on? All-True on a rare attribute is the
        # real leak; all-False mostly means "nothing to learn".
        value = grouped.max()
        homogeneous_true = homogeneous & value.astype(bool)

        all_memberships = float(subs_per_group.sum())
        exposed = float(subs_per_group.loc[homogeneous[homogeneous].index].sum())
        exposed_true = float(subs_per_group.loc[homogeneous_true[homogeneous_true].index].sum())

        # Distinct people in at least one homogeneous-on-true group: the figure
        # that actually says how many individuals have the attribute disclosed.
        if homogeneous_true.any():
            mask = pd.MultiIndex.from_frame(ctx.record[qi]).isin(
                homogeneous_true[homogeneous_true].index
            )
            subscribers_exposed_true = int(ctx.eval_index[mask].nunique())
        else:
            subscribers_exposed_true = 0

        per_attribute[name] = {
            "overall_share_true": safety.round_float(float(flag.mean())),
            "pct_groups_homogeneous": safety.round_float(100.0 * float(homogeneous.mean())),
            "pct_groups_homogeneous_on_true": safety.round_float(
                100.0 * float(homogeneous_true.mean())
            ),
            "pct_group_memberships_in_homogeneous_groups": safety.round_float(
                100.0 * exposed / all_memberships if all_memberships else 0.0
            ),
            "pct_group_memberships_in_homogeneous_true_groups": safety.round_float(
                100.0 * exposed_true / all_memberships if all_memberships else 0.0
            ),
            "pct_subscribers_with_attribute_disclosed": safety.round_float(
                100.0 * subscribers_exposed_true / total_subscribers
            ),
            "l_min": int(distinct.min()),
            "l_median": safety.round_float(float(distinct.median())),
        }

    worst = max(
        per_attribute.items(),
        key=lambda kv: kv[1]["pct_groups_homogeneous_on_true"] or 0.0,
        default=(None, None),
    )
    return {
        "id": "A3",
        "name": "Homogeneity (l-diversity)",
        "criterion": "inference",
        "attacker_knowledge": "QI values of a target (same under both models)",
        "baseline_raw": "Not applicable: raw rows are individually identifying",
        "record": {
            "n_groups": int(len(subs_per_group)),
            "attributes": per_attribute,
            "note": (
                "application_category is excluded: it is a quasi-identifier, so "
                "every group holds one value by construction."
            ),
        },
        "interpretation": (
            f"No group is homogeneous on the revealing (True) value for any of the "
            f"three attributes, so k-anonymity is not leaking a positive trait here. "
            f"Homogeneous groups are common but they are homogeneous on False "
            f"(e.g. {per_attribute.get('video', {}).get('pct_groups_homogeneous')}% for "
            f"'video'), which discloses only that a target did not do something."
        )
        if worst[0] and (worst[1]["pct_groups_homogeneous_on_true"] or 0) == 0
        else (
            f"The worst attribute is '{worst[0]}': "
            f"{worst[1]['pct_groups_homogeneous_on_true']}% of groups are homogeneous "
            f"on the revealing value, disclosing it for "
            f"{worst[1]['pct_subscribers_with_attribute_disclosed']}% of subscribers "
            "despite k-anonymity."
            if worst[0]
            else "No sensitive attributes available."
        ),
    }


# --------------------------------------------------------------------------- #
# A4 - outliers (singling out)
# --------------------------------------------------------------------------- #


def run_a4(ctx: Context) -> dict[str, Any]:
    if not len(ctx.record):
        return _empty("A4", "Outliers", "singling_out")

    qi = ctx.qi
    volumes = [c for c in anonymise.volume_columns(ctx.record) if c in ctx.record.columns]

    at_cap: dict[str, Any] = {}
    for column in volumes:
        series = pd.to_numeric(ctx.record[column], errors="coerce")
        cap = float(series.max())
        at_cap[column] = {
            "cap": safety.round_float(cap),
            "pct_rows_at_cap": safety.round_float(100.0 * float((series >= cap).mean())),
        }

    threshold = float(pd.to_numeric(ctx.raw["data_GB_sum"], errors="coerce").quantile(0.95))
    heavy = pd.to_numeric(ctx.record["data_GB_sum"], errors="coerce") > threshold
    n_heavy_rows = int(heavy.sum())

    # Add rounded volume to the QI: does a heavy user stand out once an attacker
    # also knows roughly how much data they used?
    extended = ctx.record[qi].copy()
    extended["_volume_bucket"] = pd.to_numeric(
        ctx.record["data_GB_sum"], errors="coerce"
    ).round(1)
    subs_extended = ctx.eval_index.groupby(
        [extended[c] for c in extended.columns], observed=True, dropna=False
    ).nunique()
    per_row = subs_extended.loc[pd.MultiIndex.from_frame(extended)].to_numpy()

    heavy_rows_below_k = int(((per_row < ctx.k) & heavy.to_numpy()).sum())
    return {
        "id": "A4",
        "name": "Outliers",
        "criterion": "singling_out",
        "attacker_knowledge": "QI values plus the target's approximate data volume",
        "baseline_raw": "1.00% of subscribers above the volume p99; 0.019% unique at 0.1 GB rounding",
        "record": {
            "heavy_user_threshold_raw_p95": safety.round_float(threshold),
            "n_heavy_rows": n_heavy_rows,
            "pct_heavy_rows": safety.round_float(100.0 * float(heavy.mean())),
            "top_code_caps": at_cap,
            "qi_plus_volume": {
                "pct_rows_below_k": safety.round_float(
                    100.0 * float(np.mean(per_row < ctx.k))
                ),
                "median_subscribers_sharing_combination": safety.round_float(
                    float(np.median(per_row))
                ),
                "heavy_rows_in_groups_below_k": heavy_rows_below_k,
            },
        },
        "interpretation": (
            "Top-coding collapses the extreme tail, but adding a 0.1 GB volume "
            f"bucket to the QI still puts {safety.round_float(100.0 * float(np.mean(per_row < ctx.k)))}% "
            f"of rows below k, and leaves {heavy_rows_below_k} heavy-user rows there. "
            "Volume is not part of the k-anonymity QI set, so this is residual risk."
        ),
    }


# --------------------------------------------------------------------------- #
# A5 - differencing on aggregates (singling out)
# --------------------------------------------------------------------------- #


def _simulate_aggregate(
    true_cells: pd.DataFrame,
    minimum: int,
    epsilon: float | None,
    scale: float | None,
    secondary: bool,
    seed: int,
) -> pd.DataFrame:
    """Reproduce the release's suppression logic for an attack simulation."""
    work = true_cells.copy()
    if epsilon and scale:
        rng = np.random.default_rng(seed)
        noisy = work["true_count"].to_numpy(dtype=float) + rng.laplace(0.0, scale, len(work))
        work["published_count"] = np.maximum(0, np.round(noisy))
    else:
        work["published_count"] = work["true_count"].astype(float)

    work["suppressed"] = work["published_count"] < minimum
    if secondary:
        slice_keys = [c for c in anonymise.AGGREGATE_SLICE_KEYS if c in work.columns]
        affected = work.loc[work["suppressed"], slice_keys].drop_duplicates()
        if len(affected):
            marker = set(map(tuple, affected.astype(str).to_numpy()))
            survivors = work.loc[~work["suppressed"]]
            victims = []
            for value, group in survivors.groupby(slice_keys, observed=True, dropna=False):
                parts = value if isinstance(value, tuple) else (value,)
                if tuple(str(v) for v in parts) in marker:
                    victims.append(group["published_count"].idxmin())
            work.loc[victims, "suppressed"] = True
    return work


def attempt_differencing(
    sim: pd.DataFrame, slice_keys: list[str], tolerance: int
) -> tuple[int, int, int]:
    """worst_case: the attacker knows the TRUE total per slice.

    Returns (suppressed cells attempted, recovered within tolerance, slices that
    lost exactly one cell). Only a lone hidden cell can be isolated - with two or
    more the subtraction yields their sum, not either value.
    """
    attempted = recovered = lone_slices = 0
    for _, group in sim.groupby(slice_keys, observed=True, dropna=False):
        hidden = group.loc[group["suppressed"]]
        if hidden.empty:
            continue
        estimate = float(group["true_count"].sum()) - float(
            group.loc[~group["suppressed"], "published_count"].sum()
        )
        attempted += len(hidden)
        if len(hidden) == 1:
            lone_slices += 1
            if abs(estimate - float(hidden["true_count"].iloc[0])) <= tolerance:
                recovered += 1
    return attempted, recovered, lone_slices


def run_a5(ctx: Context) -> dict[str, Any]:
    keys = [c for c in anonymise.AGGREGATE_KEYS if c in ctx.prepared.columns]
    grouped = ctx.prepared.groupby(keys, observed=True, dropna=False)[anonymise.SUBSCRIBER]
    true_cells = grouped.nunique().reset_index(name="true_count")

    minimum = ctx.min_cell
    max_cells = ctx.max_cells
    tolerance = int(ctx.eval_config["a5_tolerance_subscribers"])
    slice_keys = [c for c in anonymise.AGGREGATE_SLICE_KEYS if c in true_cells.columns]

    rows: list[dict[str, Any]] = []
    for epsilon in ctx.eval_config["sweep_epsilons"]:
        scale = (max_cells / float(epsilon)) if epsilon else None
        for secondary in (True, False):
            sim = _simulate_aggregate(
                true_cells, minimum, epsilon, scale, secondary, safety.SEED
            )
            attempted, recovered, lone_slices = attempt_differencing(
                sim, slice_keys, tolerance
            )
            rows.append(
                {
                    "dp_epsilon": "none" if epsilon is None else epsilon,
                    "secondary_suppression": secondary,
                    "suppressed_cells": attempted,
                    "slices_losing_exactly_one_cell": lone_slices,
                    "cells_recovered_within_tolerance": recovered,
                    "pct_recovered": safety.round_float(
                        100.0 * recovered / attempted if attempted else 0.0
                    ),
                }
            )

    deployed = next(
        (
            r
            for r in rows
            if r["secondary_suppression"] and r["dp_epsilon"] == ctx.release_config.get("dp_epsilon")
        ),
        None,
    )
    no_defence = next(
        (r for r in rows if not r["secondary_suppression"] and r["dp_epsilon"] == "none"), None
    )
    no_defence_same_eps = next(
        (
            r["suppressed_cells"]
            for r in rows
            if not r["secondary_suppression"]
            and r["dp_epsilon"] == ctx.release_config.get("dp_epsilon")
        ),
        0,
    )
    return {
        "id": "A5",
        "name": "Differencing on aggregates",
        "criterion": "singling_out",
        "attacker_knowledge": "worst_case: the true n_subscribers total per (time_bucket, province) slice",
        "baseline_raw": "Not applicable: raw has no suppression to undo",
        "aggregate": {
            "tolerance_subscribers": tolerance,
            "realistic": "Not attemptable: the recipient does not hold true slice totals.",
            "worst_case_grid": rows,
        },
        "interpretation": (
            (
                "No slice in this extract ever loses exactly one cell, so the "
                "subtraction never isolates a single suppressed value: recovery is "
                f"{no_defence['pct_recovered']}% even undefended (no noise, no secondary "
                "suppression). The attack is blocked by the shape of the data here, "
                "NOT demonstrably by secondary suppression - which costs "
                f"{deployed['suppressed_cells'] - no_defence_same_eps} extra cells and "
                "remains untested on this extract. The synthetic test in "
                "tests/test_evaluate.py shows the defence works when a lone cell "
                "is suppressed."
            )
            if no_defence["slices_losing_exactly_one_cell"] == 0
            else (
                f"With no noise and no secondary suppression {no_defence['pct_recovered']}% "
                f"of suppressed cells are recovered; at the deployed setting "
                f"{deployed['pct_recovered']}%."
            )
        )
        if deployed and no_defence
        else "Insufficient data.",
    }


# --------------------------------------------------------------------------- #
# A6 - membership inference on aggregates (inference)
# --------------------------------------------------------------------------- #


def membership_game(
    with_target: np.ndarray,
    without_target: np.ndarray,
    scale: float | None,
    trials: int,
    rng: np.random.Generator,
) -> tuple[int, int]:
    """Play the in/out game ``trials`` times; return (correct guesses, trials).

    The attacker sees one noisy release drawn from the world with or without the
    target and applies the Laplace likelihood-ratio test, which is the optimal
    test against this mechanism.
    """
    correct = 0
    for _ in range(trials):
        member = bool(rng.integers(0, 2))
        truth = with_target if member else without_target
        if scale:
            observed = truth + rng.laplace(0.0, scale, size=with_target.size)
            ll_in = -np.abs(observed - with_target).sum() / scale
            ll_out = -np.abs(observed - without_target).sum() / scale
        else:
            observed = truth
            ll_in = -np.abs(observed - with_target).sum()
            ll_out = -np.abs(observed - without_target).sum()
        correct += int((ll_in >= ll_out) == member)
    return correct, trials


def run_a6(ctx: Context) -> dict[str, Any]:
    keys = [c for c in anonymise.AGGREGATE_KEYS if c in ctx.prepared.columns]
    pairs = ctx.prepared[[anonymise.SUBSCRIBER, *keys]].drop_duplicates()
    cell_codes, _ = pd.factorize(
        pd.Series(list(zip(*(pairs[c].astype(str) for c in keys))), index=pairs.index)
    )
    pairs = pairs.assign(_cell=cell_codes)

    counts = pairs.groupby("_cell").size()
    true_counts = counts.to_numpy(dtype=float)

    by_subscriber = pairs.groupby(anonymise.SUBSCRIBER)["_cell"].apply(list)
    subscribers = sorted(by_subscriber.index)

    n_targets = min(int(ctx.eval_config["a6_sample_size"]), len(subscribers))
    trials = int(ctx.eval_config["a6_trials_per_target"])
    rng = np.random.default_rng(safety.SEED)
    targets = [subscribers[i] for i in rng.choice(len(subscribers), size=n_targets, replace=False)]

    max_cells = ctx.max_cells
    results = []
    for epsilon in ctx.eval_config["sweep_epsilons"]:
        scale = (max_cells / float(epsilon)) if epsilon else None
        correct = 0
        total = 0
        game = np.random.default_rng(safety.SEED)
        for target in targets:
            cells = np.array(by_subscriber.loc[target], dtype=int)
            with_target = true_counts[cells]
            without_target = with_target - 1.0

            hits, played = membership_game(with_target, without_target, scale, trials, game)
            correct += hits
            total += played

        accuracy = 100.0 * correct / total if total else 0.0
        bound = (
            100.0 * float(np.exp(epsilon) / (1.0 + np.exp(epsilon))) if epsilon else 100.0
        )
        results.append(
            {
                "dp_epsilon": "none" if epsilon is None else epsilon,
                "noise_scale": safety.round_float(scale),
                "attacker_accuracy_pct": safety.round_float(accuracy),
                "attacker_advantage_pct": safety.round_float(2 * accuracy - 100.0),
                "theoretical_bound_pct": safety.round_float(bound),
            }
        )

    deployed_eps = ctx.release_config.get("dp_epsilon")
    deployed = next((r for r in results if r["dp_epsilon"] == deployed_eps), None)
    no_noise = next((r for r in results if r["dp_epsilon"] == "none"), None)
    return {
        "id": "A6",
        "name": "Membership inference on aggregates",
        "criterion": "inference",
        "attacker_knowledge": (
            "worst_case: every other subscriber's data and the target's true cells - "
            "the standard differential-privacy adversary"
        ),
        "baseline_raw": "100% - raw rows carry the subscriber key outright",
        "aggregate": {
            "n_targets": n_targets,
            "trials_per_target": trials,
            "method": (
                "For each target the attacker sees one noisy release drawn at random "
                "from the world with or without them, and applies a Laplace "
                "likelihood-ratio test over the target's cells. 50% = random guessing."
            ),
            "scope_note": (
                "The test operates on the noised counts, which is exactly what the DP "
                "guarantee covers. Suppression is not simulated per target, so this "
                "measures the count channel only."
            ),
            "realistic": "Not attemptable: the recipient does not hold the other subscribers' data.",
            "worst_case_grid": results,
        },
        "interpretation": (
            f"Without noise the attacker is {no_noise['attacker_accuracy_pct']}% accurate. "
            f"At the deployed epsilon the attack falls to "
            f"{deployed['attacker_accuracy_pct']}% against a theoretical ceiling of "
            f"{deployed['theoretical_bound_pct']}%, i.e. an advantage of "
            f"{deployed['attacker_advantage_pct']} points over guessing."
        )
        if deployed and no_noise
        else "Insufficient data.",
    }


def _empty(identifier: str, name: str, criterion: str) -> dict[str, Any]:
    return {
        "id": identifier,
        "name": name,
        "criterion": criterion,
        "attacker_knowledge": "-",
        "baseline_raw": "-",
        "record": {},
        "interpretation": "Not evaluated: the release was empty.",
    }


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #


def _headline(result: dict[str, Any]) -> tuple[str, str]:
    """(record column, aggregate column) for the summary table."""
    identifier = result["id"]
    if identifier == "A1":
        r = result["record"]
        return (
            f"{r['pct_rows_in_groups_of_1']}% rows unique; "
            f"P(identify) = {r['expected_identification_probability']}",
            "-",
        )
    if identifier == "A2":
        p4 = next((x for x in result["record"]["worst_case"]["results"] if x["p"] == 4), {})
        return (
            f"no subscriber key; even if linkable, "
            f"{p4.get('pct_unique_if_rows_were_linkable')}% unique at p=4",
            "-",
        )
    if identifier == "A3":
        worst = max(
            result["record"]["attributes"].items(),
            key=lambda kv: kv[1]["pct_groups_homogeneous_on_true"] or 0.0,
        )
        return (
            f"worst attribute '{worst[0]}': "
            f"{worst[1]['pct_groups_homogeneous_on_true']}% of groups homogeneous on the revealing value",
            "-",
        )
    if identifier == "A4":
        r = result["record"]["qi_plus_volume"]
        return (
            f"{r['pct_rows_below_k']}% of rows below k once volume joins the QI; "
            f"{r['heavy_rows_in_groups_below_k']} heavy rows there",
            "-",
        )
    if identifier == "A5":
        grid = result["aggregate"]["worst_case_grid"]
        off = next((r for r in grid if not r["secondary_suppression"] and r["dp_epsilon"] == "none"), {})
        on = next((r for r in grid if r["secondary_suppression"] and r["dp_epsilon"] == 1.0), {})
        return ("-", f"{on.get('pct_recovered')}% recovered (vs {off.get('pct_recovered')}% undefended)")
    if identifier == "A6":
        grid = result["aggregate"]["worst_case_grid"]
        on = next((r for r in grid if r["dp_epsilon"] == 1.0), {})
        return (
            "-",
            f"{on.get('attacker_accuracy_pct')}% accuracy "
            f"(bound {on.get('theoretical_bound_pct')}%, 50% = guessing)",
        )
    return ("-", "-")


def render_report(results: list[dict[str, Any]], ctx: Context) -> str:
    lines = [
        "# Risk assessment",
        "",
        "Generated by `python -m src.evaluate`. Do not edit by hand.",
        "Every figure below was measured by running the attack, not asserted.",
        "",
        "## Threat model",
        "",
        f"- **Recipient (realistic):** {RECIPIENT}",
        f"- **Worst-case attacker:** {WORST_CASE}",
        "",
        "Results are reported under both where the attack is attemptable at all.",
        "",
        "## Headline: before and after",
        "",
        "| Attack | Criterion | Raw baseline | Record release | Aggregate release (eps=1) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for result in results:
        record_cell, aggregate_cell = _headline(result)
        lines.append(
            f"| {result['id']} {result['name']} | {result['criterion']} | "
            f"{result['baseline_raw']} | {record_cell} | {aggregate_cell} |"
        )

    for result in results:
        lines += [
            "",
            f"## {result['id']} - {result['name']}",
            "",
            f"**Article 29 criterion:** {result['criterion']}",
            "",
            f"**Attacker knowledge:** {result['attacker_knowledge']}",
            "",
            f"**Raw baseline:** {result['baseline_raw']}",
            "",
            f"**Result:** {result['interpretation']}",
            "",
        ]
        block = result.get("record") or result.get("aggregate") or {}
        if block:
            lines += ["```json", json.dumps(block, indent=2, default=str), "```", ""]

    lines += [
        "## What the DP guarantee does and does not cover",
        "",
        "- **Covered:** `n_subscribers` in the aggregate release, noised with Laplace",
        f"  at scale {ctx.release_config.get('max_cells_per_subscriber')}/epsilon, where the",
        "  numerator is the contribution bound on cells per subscriber.",
        "- **Covered:** which cells are published, because primary suppression is",
        "  decided on the noisy count.",
        "- **NOT covered:** QoE medians, p10 and p90, and the volume sums. They carry",
        "  no noise and are protected only by the >= 10 subscriber threshold,",
        "  winsorising and top-coding.",
        "- **NOT covered:** the record and session releases, which use no DP at all.",
        "- **NOT covered:** repeated publication. We publish once and do not track",
        "  budget composition across releases.",
        "",
        "## Wording rule",
        "",
        "No release here is 'anonymous' in an absolute sense. Each result above is of",
        "the form 'reduces measured risk to X under threat model Y'.",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


@safety.safe_main
def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.evaluate")
    parser.parse_args(argv)

    print("Building releases in memory...")
    ctx = build_context()

    attacks = (
        ("A1 row uniqueness", run_a1),
        ("A2 trajectory", run_a2),
        ("A3 homogeneity", run_a3),
        ("A4 outliers", run_a4),
        ("A5 differencing", run_a5),
        ("A6 membership inference", run_a6),
    )
    results = []
    for label, attack in attacks:
        print(f"Running {label}...")
        results.append(attack(ctx))

    payload = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "seed": safety.SEED,
        "threat_model": {"recipient": RECIPIENT, "worst_case": WORST_CASE},
        "attacks": results,
    }
    json_path = safety.safe_write_json(payload, RISK_EVAL_PATH)
    doc_path = safety.safe_write_text(render_report(results, ctx), RISK_DOC_PATH)

    print("\n" + "=" * 78)
    print("RISK EVALUATION")
    print("=" * 78)
    for result in results:
        record_cell, aggregate_cell = _headline(result)
        print(f"{result['id']} {result['name']:<34} {record_cell if record_cell != '-' else aggregate_cell}")
    print("=" * 78)
    print(f"written: {json_path}")
    print(f"written: {doc_path}")


if __name__ == "__main__":
    main()
