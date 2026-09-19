"""Shared tool harness for the AI Analyst and AI Red Team pages (M6.3).

``query_aggregate`` is the only data tool either agent gets: it runs pandas
locally on the published aggregate release and refuses to return any cell
with fewer than ``MIN_SUBSCRIBERS_PER_CELL`` subscribers. No arbitrary code
execution, and no path to raw data — it only ever touches what
``data.load_aggregate_release`` hands it.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from . import data

MIN_SUBSCRIBERS_PER_CELL = data.MIN_SUBSCRIBERS_PER_CELL


class RefusedQuery(Exception):
    """Raised when a query is malformed or its result would expose a cell
    with fewer than MIN_SUBSCRIBERS_PER_CELL subscribers."""


def query_aggregate(
    filters: dict[str, Any],
    group_by: list[str],
    metrics: list[str],
) -> pd.DataFrame:
    df = data.load_aggregate_release()
    if df is None:
        raise RefusedQuery("aggregate release not found (outputs/releases/aggregate.parquet)")

    for column, value in (filters or {}).items():
        if column not in df.columns:
            raise RefusedQuery(f"unknown filter column: {column}")
        if isinstance(value, (list, tuple, set)):
            df = df[df[column].isin(value)]
        else:
            df = df[df[column] == value]

    unknown_group_cols = [c for c in (group_by or []) if c not in df.columns]
    if unknown_group_cols:
        raise RefusedQuery(f"unknown group_by column(s): {unknown_group_cols}")
    known_metrics = [m for m in (metrics or []) if m in df.columns]

    if group_by:
        result = df.groupby(group_by, as_index=False).agg(
            n_subscribers=("n_subscribers", "sum"),
            **{metric: (metric, "mean") for metric in known_metrics},
        )
    else:
        row = {"n_subscribers": df["n_subscribers"].sum()}
        row.update({metric: df[metric].mean() for metric in known_metrics})
        result = pd.DataFrame([row])

    if (result["n_subscribers"] < MIN_SUBSCRIBERS_PER_CELL).any():
        raise RefusedQuery(
            f"result contains a cell with fewer than {MIN_SUBSCRIBERS_PER_CELL} subscribers"
        )
    return result


def run_agent(mode: str, question: str) -> dict:
    """TODO (M6.3 stretch goal): a tool-calling loop over safety.llm_gateway,
    max 6 steps, with query_aggregate as the only data tool.

    mode="analyst": answers aggregate questions with a short answer, the
    table used, and a caveat line (DP noise, suppressed cells, means not
    supported for QoE metrics).

    mode="red_team": given the release schema and an attacker-knowledge
    TEMPLATE (never real target values), proposes a re-identification
    strategy as a sequence of tool queries. The harness runs that strategy
    locally against 200 sampled targets (evaluation index kept in memory
    only) and returns just the success rate.
    """
    raise NotImplementedError("M6.3 stretch goal — not built yet")
