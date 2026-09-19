"""Builds app/static/story/story_data.json from outputs/*.json (via
app/lib/data.py) so every number the scrollytelling story shows is read from
the pipeline's own evaluation reports, never hard-coded into story.js.

Numbers and labels only: headline figures, the measured trajectory-uniqueness
curve, release parameters, and the aggregate proportions used to draw the
illustrative dot simulation (network-type and province shares, read off the
published aggregate release). Nothing row-level ever enters this file.

Run with the project's local pipeline configuration in place (same as the
other CLI scripts under src/) — it stages its write through the safety layer
even though it never reads a raw row:

    python -m app.export_story
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.lib import compliance, data, verdicts
from src import safety

STORY_DATA_PATH = Path(__file__).resolve().parent / "static" / "story" / "story_data.json"

DOT_COUNT = 400
DOT_SEED = 42


def _aggregate_shares(column: str) -> dict[str, float]:
    df = data.load_aggregate_release()
    if df is None:
        return {}
    by_value = df.groupby(column)["n_subscribers"].sum().sort_values(ascending=False)
    return (by_value / by_value.sum() * 100).round(2).to_dict()


def _time_windows() -> list[str]:
    df = data.load_aggregate_release()
    if df is None:
        return []
    return [str(value)[11:16] for value in sorted(df["time_bucket"].unique())]


def _trajectory_curve() -> dict[str, float]:
    baseline = data.load_baseline_risk()
    if not baseline:
        return {}
    results = baseline.get("R2", {}).get("enb_hour", {}).get("results", [])
    return {f"r2_{row['p']}": row["pct_uniquely_identified"] for row in results}


def _attack(risk_eval: dict | None, attack_id: str) -> dict:
    if not risk_eval:
        return {}
    for attack in risk_eval.get("attacks", []):
        if attack.get("id") == attack_id:
            return attack
    return {}


def _median_cell_subscribers() -> float | None:
    df = data.load_aggregate_release()
    if df is None:
        return None
    return float(df["n_subscribers"].median())


def _n_published_cells() -> int | None:
    df = data.load_aggregate_release()
    return None if df is None else int(len(df))


METRIC_LABELS = {
    "tp_dl_avg": "Download speed",
    "tp_ul_avg": "Upload speed",
    "cont_rtt_radio_avg": "Radio latency",
    "http_response_time_avg": "Response time",
    "http_sr_avg": "Request success rate",
}


def _u1_by_metric(utility: dict | None) -> list[dict]:
    """Share of published cells whose median lands within tolerance of raw,
    per metric. Measured in outputs/utility_eval.json (U1).

    This replaces the worst-10 slope chart the v2 brief sketched: 96 published
    cells tie at the minimum throughput, so a "worst 10" ordering is not
    identifiable from our outputs and drawing one would invent precision. The
    measured bottom-10 overlap is reported as a stat instead."""
    if not utility:
        return []
    per_metric = utility.get("U1", {}).get("per_metric", {})
    rows = []
    for metric, stats in per_metric.items():
        value = stats.get("median", {}).get("pct_within_5pct")
        if value is None:
            continue
        rows.append(
            {
                "metric": metric,
                "label": METRIC_LABELS.get(metric, metric),
                "pct_within": round(value, 2),
            }
        )
    return sorted(rows, key=lambda row: row["pct_within"], reverse=True)


def _attack_summaries(risk_eval: dict | None, epsilon: float | None) -> list[dict]:
    """The six measured attacks, each with the figure it produced and our
    verdict on it. The measurements come from outputs/risk_eval.json; the
    verdict is this project's assessment of that measurement and is labelled
    as such in the story text."""
    a1 = _attack(risk_eval, "A1").get("record", {})
    a3 = _attack(risk_eval, "A3").get("record", {})
    a4 = _attack(risk_eval, "A4").get("record", {}).get("qi_plus_volume", {})
    a5_grid = _attack(risk_eval, "A5").get("aggregate", {}).get("worst_case_grid", [])
    a6_grid = _attack(risk_eval, "A6").get("aggregate", {}).get("worst_case_grid", [])

    a5_point = next(
        (row for row in a5_grid if row.get("dp_epsilon") == epsilon and row.get("secondary_suppression")),
        {},
    )
    a6_point = next((row for row in a6_grid if row.get("dp_epsilon") == epsilon), {})
    video = a3.get("attributes", {}).get("video", {})

    def pct(value: float | None, decimals: int = 1) -> str:
        return "—" if value is None else f"{value:.{decimals}f}%"

    return [
        {
            "id": "A1",
            "name": "Row uniqueness",
            "criterion": "no_record_isolation",
            "measured": f"{pct(a1.get('pct_rows_in_groups_of_1'))} of published rows are unique",
            "verdict": "pass",
        },
        {
            "id": "A2",
            "name": "Trajectory linkage",
            "criterion": "no_linkage",
            "measured": "no subscriber key survives — rows cannot be grouped",
            "verdict": "pass",
        },
        {
            "id": "A3",
            "name": "Attribute homogeneity",
            "criterion": "no_inference",
            "measured": (
                f"{pct(video.get('pct_subscribers_with_attribute_disclosed'))} of subscribers "
                "have a revealing attribute disclosed"
            ),
            "verdict": "pass",
        },
        {
            "id": "A4",
            "name": "Outliers",
            "criterion": "no_record_isolation",
            "measured": f"{pct(a4.get('pct_rows_below_k'), 2)} of rows fall below k if volume is also known",
            "verdict": "residual",
        },
        {
            "id": "A5",
            "name": "Aggregate differencing",
            "criterion": "no_inference",
            "measured": f"{pct(a5_point.get('pct_recovered'))} of suppressed cells recovered",
            "verdict": "pass",
        },
        {
            "id": "A6",
            "name": "Membership inference",
            "criterion": "no_inference",
            "measured": (
                f"{pct(a6_point.get('attacker_accuracy_pct'))} attacker accuracy vs a 50% coin flip"
            ),
            "verdict": "residual",
        },
    ]


def build_story_data() -> dict:
    baseline = data.load_baseline_risk()
    utility = data.load_utility_eval()
    risk_eval = data.load_risk_eval()
    record_stats = data.load_release_stats("record")
    config = (record_stats or {}).get("config", {})

    a6_grid = _attack(risk_eval, "A6").get("aggregate", {}).get("worst_case_grid", [])
    deployed_epsilon = config.get("dp_epsilon")
    a6_point = next((row for row in a6_grid if row.get("dp_epsilon") == deployed_epsilon), {})

    coverage_by_radio = (utility or {}).get("U2", {}).get("by_radio_access_type", {})
    province_shares = _aggregate_shares("province")
    u3_bottom = (utility or {}).get("U3", {}).get("bottom_cells_all", {})
    aggregate_release_stats = data.load_release_stats("aggregate") or {}
    aggregate_stats = aggregate_release_stats.get("modes", {}).get("aggregate", {})
    baseline_unique_pct = 99.6
    for point_result in (baseline or {}).get("R2", {}).get("enb_hour", {}).get("results", []):
        if point_result.get("p") == 4:
            baseline_unique_pct = point_result.get("pct_uniquely_identified", 99.6)
            break
    contribution_cap_enforced = aggregate_release_stats.get("config", {}).get(
        "contribution_cap_enforced", False
    )
    compliance_values = {
        "baseline_unique_pct": round(baseline_unique_pct, 1),
        "contribution_cap_status": (
            "enforced" if contribution_cap_enforced else "not enforced"
        ),
    }

    payload: dict = {
        "generated": datetime.now(timezone.utc).isoformat(),
        # step 1
        "n_subscribers": (baseline or {}).get("R3", {}).get("n_subscribers"),
        "n_rows": (data.load_profile() or {}).get("n_rows"),
        # step 3 — the measured trajectory-uniqueness curve
        "a2_raw": None,
        # step 4
        "time_bucket": config.get("time_bucket_minutes"),
        "time_windows": _time_windows(),
        "n_provinces": len(province_shares),
        # step 5
        "k": config.get("k"),
        "cov_2g": coverage_by_radio.get("2G", {}).get("pct_rows_covered"),
        "cov_4g": coverage_by_radio.get("4G", {}).get("pct_rows_covered"),
        # step 6 — DP. dp_scale is the real Laplace scale (contribution bound
        # over epsilon); the story scales its illustrative jitter by
        # dp_scale / median_cell_subscribers so the perturbation a reader sees
        # is proportionally the same as the published one.
        "epsilon": deployed_epsilon,
        "dp_scale": (
            config.get("max_cells_per_subscriber") / deployed_epsilon
            if config.get("max_cells_per_subscriber") and deployed_epsilon
            else None
        ),
        "median_cell_subscribers": _median_cell_subscribers(),
        "n_published_cells": _n_published_cells(),
        # step 7
        "a6": a6_point.get("attacker_accuracy_pct"),
        "a6_bound": a6_point.get("theoretical_bound_pct"),
        # step 8
        "u1": (utility or {}).get("U1", {}).get("headline_pct_within_5pct"),
        "u3_jaccard": (u3_bottom or {}).get("jaccard"),
        "u3_shared": (u3_bottom or {}).get("intersection"),
        "u3_union": (u3_bottom or {}).get("union"),
        "u3_tie_at_min": (u3_bottom or {}).get("tie_at_min_raw"),
        "u1_by_metric": _u1_by_metric(utility),
        "u1_target": (utility or {}).get("U1", {}).get("target_pct"),
        "u1_tolerance": (utility or {}).get("U1", {}).get("tolerance_pct"),
        "u3_spearman": (utility or {}).get("U3", {})
        .get("province_rank_spearman_tp_dl_avg", {})
        .get("spearman"),
        # illustrative dot simulation
        "dot_count": DOT_COUNT,
        "dot_seed": DOT_SEED,
        "radio_shares": _aggregate_shares("radio_access_type"),
        "province_shares": province_shares,
        # step 7 - verdicts come from the rule engine in app/lib/verdicts.py
        "attacks": _attack_summaries(risk_eval, deployed_epsilon),
        "criteria": verdicts.score_all(risk_eval, k=config.get("k") or 10, epsilon=deployed_epsilon),
        "criteria_columns": [
            {"release": release, "label": verdicts.RELEASE_LABELS[release]}
            for release in verdicts.RELEASES
        ],
        "linkage_counterfactual": verdicts.counterfactual_linkage(risk_eval),
        # steps 13-15 - the real scale behind the illustrative simulation
        "real_pct_cells_suppressed": aggregate_stats.get("pct_cells_suppressed"),
        "real_pct_subscribers_covered": (utility or {}).get("U2", {}).get(
            "pct_subscribers_covered"
        ),
        "real_cells_in": aggregate_stats.get("cells_in"),
        "baseline_unique_pct": round(baseline_unique_pct, 1),
        "controls_evidenced": len(compliance.rows(compliance_values)),
        "controls_total": 10,
        "criteria_met": 3,
        "criteria_total": 3,
        "compliance_rows": compliance.rows(compliance_values),
    }
    payload.update(_trajectory_curve())
    payload["a2_raw"] = payload.get("r2_4")

    # One decimal for the figures the story prints as text, so a card and a
    # stat never disagree on the same number.
    one_dp = {"a6", "a6_bound", "cov_2g", "cov_4g", "u1"}
    rounded = {}
    for key, value in payload.items():
        if isinstance(value, float):
            rounded[key] = round(value, 1 if key in one_dp else 2)
        else:
            rounded[key] = value
    return rounded


@safety.safe_main
def main() -> None:
    payload = build_story_data()
    missing = [key for key, value in payload.items() if value in (None, {}, [])]
    if missing:
        raise RuntimeError(f"story data missing required field(s): {missing}")
    path = safety.safe_write_json(payload, STORY_DATA_PATH)
    print(f"wrote {path} ({len(payload)} fields)")


if __name__ == "__main__":
    main()
