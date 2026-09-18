"""Baseline re-identification risk of the raw dataset.

Three families of measurement, all reported as aggregates:

* **R1 - row uniqueness** for four quasi-identifier sets.
* **R2 - trajectory uniqueness** under two definitions of a "point".
* **R3 - outlier exposure** from volume, tethering and device model.

The subscriber key is ``msisdn`` and stays in memory only; nothing derived from
an identifier value reaches ``outputs/baseline_risk.json``.

Run with::

    python -m src.baseline_risk
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src import safety

OUTPUT_PATH = "outputs/baseline_risk.json"

QI_SETS: dict[str, list[str]] = {
    "A": ["time_start", "enb"],
    "B": ["time_start", "enb", "tac"],
    "C": ["province", "radio_access_type", "application_category", "tac"],
    "D": ["time_start", "enb", "radio_access_type", "application_category", "tac"],
}

#: Subscribers sampled per trajectory length.
TRAJECTORY_SAMPLE = 1000
#: Trajectory lengths (number of points an attacker is assumed to know).
TRAJECTORY_LENGTHS = (1, 2, 3, 4)

_f = safety.round_float


def _pct(value) -> float | None:
    """Convert a share in [0, 1] to a rounded percentage."""
    out = safety.round_float(value)
    return None if out is None else safety.round_float(out * 100.0)


# --------------------------------------------------------------------------- #
# R1 - row uniqueness
# --------------------------------------------------------------------------- #


def row_uniqueness(df: pd.DataFrame, qi: list[str]) -> dict[str, object]:
    """Group sizes under a quasi-identifier set."""
    sizes = df.groupby(qi, observed=True, dropna=False)["msisdn"].transform("size")
    n_subscribers = df["msisdn"].nunique()
    unique_rows = sizes == 1
    exposed = df.loc[unique_rows, "msisdn"].nunique()

    return {
        "qi": list(qi),
        "n_groups": int(df.groupby(qi, observed=True, dropna=False).ngroups),
        "pct_rows_in_groups_of_1": _pct(unique_rows.mean()),
        "pct_rows_in_groups_lt_5": _pct((sizes < 5).mean()),
        "min_group_size": int(sizes.min()),
        "pct_subscribers_with_ge1_unique_row": _pct(exposed / n_subscribers),
    }


def run_r1(df: pd.DataFrame) -> dict[str, object]:
    return {name: row_uniqueness(df, qi) for name, qi in QI_SETS.items()}


# --------------------------------------------------------------------------- #
# R2 - trajectory uniqueness
# --------------------------------------------------------------------------- #


def _build_index(
    df: pd.DataFrame, point_columns: list[str]
) -> tuple[dict[object, set[str]], dict[str, list[object]]]:
    """Return ``point -> subscribers`` and ``subscriber -> distinct points``."""
    pairs = df[["msisdn"] + point_columns].drop_duplicates()
    points = list(zip(*(pairs[column] for column in point_columns)))

    point_to_subs: dict[object, set[str]] = {}
    sub_to_points: dict[str, list[object]] = {}
    for subscriber, point in zip(pairs["msisdn"].tolist(), points):
        point_to_subs.setdefault(point, set()).add(subscriber)
        sub_to_points.setdefault(subscriber, []).append(point)
    return point_to_subs, sub_to_points


def trajectory_uniqueness(
    df: pd.DataFrame, point_columns: list[str], label: str
) -> dict[str, object]:
    """Share of sampled subscribers uniquely pinned down by ``p`` known points."""
    point_to_subs, sub_to_points = _build_index(df, point_columns)
    results: list[dict[str, object]] = []

    for p in TRAJECTORY_LENGTHS:
        eligible = sorted(sub for sub, pts in sub_to_points.items() if len(pts) >= p)
        if not eligible:
            results.append(
                {
                    "p": p,
                    "n_eligible_subscribers": 0,
                    "n_sampled": 0,
                    "pct_uniquely_identified": None,
                }
            )
            continue

        rng = np.random.default_rng(safety.SEED)
        take = min(TRAJECTORY_SAMPLE, len(eligible))
        sampled = [eligible[i] for i in rng.choice(len(eligible), size=take, replace=False)]

        cache: dict[frozenset, int] = {}
        unique = 0
        for subscriber in sampled:
            points = sorted(sub_to_points[subscriber], key=repr)
            chosen = [points[i] for i in rng.choice(len(points), size=p, replace=False)]
            key = frozenset(chosen)
            count = cache.get(key)
            if count is None:
                sets = sorted((point_to_subs[point] for point in chosen), key=len)
                matched = set(sets[0])
                for other in sets[1:]:
                    matched &= other
                    if not matched:
                        break
                count = len(matched)
                cache[key] = count
            if count == 1:
                unique += 1

        results.append(
            {
                "p": p,
                "n_eligible_subscribers": len(eligible),
                "n_sampled": take,
                "pct_uniquely_identified": _pct(unique / take),
            }
        )

    return {
        "point_definition": label,
        "point_columns": list(point_columns),
        "n_distinct_points": len(point_to_subs),
        "results": results,
    }


def run_r2(df: pd.DataFrame) -> dict[str, object]:
    work = df.copy()
    work["_hour"] = work["time_start"].dt.floor("h")
    work["_date"] = work["time_start"].dt.date
    return {
        "enb_hour": trajectory_uniqueness(work, ["enb", "_hour"], "(enb, time_start floored to hour)"),
        "province_date": trajectory_uniqueness(work, ["province", "_date"], "(province, date)"),
    }


# --------------------------------------------------------------------------- #
# R3 - outliers
# --------------------------------------------------------------------------- #


def run_r3(df: pd.DataFrame) -> dict[str, object]:
    totals = df.groupby("msisdn", observed=True)["data_GB_sum"].sum()
    n_subscribers = len(totals)

    p99 = totals.quantile(0.99)
    rounded = totals.round(1)
    rounded_counts = rounded.value_counts()
    unique_rounded = rounded.map(rounded_counts).eq(1)

    tethering = df.groupby("msisdn", observed=True)["tethering_data_GB_dl_sum"].max()

    subs_per_tac = df.groupby("tac", observed=True)["msisdn"].nunique()
    rare_tacs = set(subs_per_tac[subs_per_tac < 5].index)
    sub_tac = df.drop_duplicates(subset=["msisdn", "tac"])
    subs_with_rare_tac = sub_tac.loc[sub_tac["tac"].isin(rare_tacs), "msisdn"].nunique()

    return {
        "n_subscribers": int(n_subscribers),
        "total_data_GB_per_subscriber": {
            "p99": _f(p99),
            "max": _f(totals.max()),
            "pct_above_p99": _pct((totals > p99).mean()),
            "pct_unique_when_rounded_to_0_1_GB": _pct(unique_rounded.mean()),
        },
        "pct_subscribers_with_any_tethering": _pct((tethering > 0).mean()),
        "device_model": {
            "n_distinct_tac": int(subs_per_tac.size),
            "n_tac_with_lt5_subscribers": int(len(rare_tacs)),
            "pct_subscribers_in_tac_lt5": _pct(subs_with_rare_tac / n_subscribers),
        },
    }


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def print_report(report: dict) -> None:
    print("=" * 78)
    print("BASELINE RE-IDENTIFICATION RISK")
    print("=" * 78)
    context = report["context"]
    print(f"rows {context['n_rows']:,} | subscribers {context['n_subscribers']:,}")

    print("\nR1  Row uniqueness by quasi-identifier set")
    header = f"{'set':<4} {'%rows k=1':>10} {'%rows k<5':>10} {'min k':>7} {'%subs w/ unique row':>21}  qi"
    print(header)
    print("-" * len(header))
    for name, res in report["R1"].items():
        print(
            f"{name:<4} {res['pct_rows_in_groups_of_1']:>10.2f} {res['pct_rows_in_groups_lt_5']:>10.2f} "
            f"{res['min_group_size']:>7} {res['pct_subscribers_with_ge1_unique_row']:>21.2f}  {'+'.join(res['qi'])}"
        )

    print("\nR2  Trajectory uniqueness (% of sampled subscribers pinned to exactly 1)")
    header = f"{'point':<14} {'p':>2} {'eligible':>10} {'sampled':>8} {'% unique':>9}"
    print(header)
    print("-" * len(header))
    for key, block in report["R2"].items():
        for res in block["results"]:
            pct = res["pct_uniquely_identified"]
            pct_text = "n/a" if pct is None else f"{pct:.2f}"
            print(
                f"{key:<14} {res['p']:>2} {res['n_eligible_subscribers']:>10,} "
                f"{res['n_sampled']:>8,} {pct_text:>9}"
            )

    print("\nR3  Outlier exposure")
    r3 = report["R3"]
    volume = r3["total_data_GB_per_subscriber"]
    print(f"  % subscribers above volume p99            : {volume['pct_above_p99']:.2f}")
    print(f"  % subscribers unique at 0.1 GB rounding   : {volume['pct_unique_when_rounded_to_0_1_GB']:.2f}")
    print(f"  % subscribers with any tethering          : {r3['pct_subscribers_with_any_tethering']:.2f}")
    print(f"  % subscribers in a tac with <5 subscribers: {r3['device_model']['pct_subscribers_in_tac_lt5']:.2f}")
    print("=" * 78)
    for note in report["notes"]:
        print(f"NOTE: {note}")


def collect_notes(df: pd.DataFrame) -> list[str]:
    """Data properties that materially change how the numbers should be read."""
    notes: list[str] = []
    if df["tac"].nunique() <= 1:
        notes.append(
            "tac is constant across the whole dataset, so it adds no separating power "
            "to QI sets B/C/D and R3's rare-device measure is structurally zero."
        )
    n_days = df["time_start"].dt.date.nunique()
    n_hours = df["time_start"].dt.floor("h").nunique()
    if n_days <= 1:
        notes.append(
            f"The extract covers a single date ({n_days} day, {n_hours} distinct hour(s)), "
            "so the (province, date) trajectory collapses to province alone."
        )
    return notes


@safety.safe_main
def main() -> None:
    df = safety.add_tac(safety.load_raw())
    report = {
        "seed": safety.SEED,
        "context": {"n_rows": int(len(df)), "n_subscribers": int(df["msisdn"].nunique())},
        "R1": run_r1(df),
        "R2": run_r2(df),
        "R3": run_r3(df),
        "notes": collect_notes(df),
    }
    path = safety.safe_write_json(report, OUTPUT_PATH)
    print_report(report)
    print(f"written: {path}")


if __name__ == "__main__":
    main()
