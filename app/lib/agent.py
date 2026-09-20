"""Shared tool harness for the AI Analyst page.

``query_aggregate`` is the only data tool either agent gets: it runs pandas
locally on the published aggregate release and refuses to return any cell
with fewer than ``MIN_SUBSCRIBERS_PER_CELL`` subscribers. No arbitrary code
execution, and no path to raw data — it only ever touches what
``data.load_aggregate_release`` hands it.

Two things the tool is deliberately explicit about, because the model cannot
infer either one and both produce confidently wrong answers:

* the subscriber column it returns is a **sum over cells**, so a subscriber
  present in several cells is counted once per cell. It is named
  ``n_subscriber_cells`` for that reason and is never a distinct headcount.
* the units of the throughput, RTT and HTTP-response-time columns are not
  documented in ``docs/dataset_description.txt``, so the model is told to
  report those numbers bare rather than invent "Mbps" or "ms".
"""
from __future__ import annotations

import json
from typing import Any

import pandas as pd

from . import data

MIN_SUBSCRIBERS_PER_CELL = data.MIN_SUBSCRIBERS_PER_CELL

#: The name under which the summed subscriber count leaves the tool. Renamed
#: from ``n_subscribers`` so nothing downstream reads it as a headcount.
COUNT_COLUMN = "n_subscriber_cells"

#: Columns a query may group by. Everything else in the release is a metric.
GROUP_COLUMNS = ("time_bucket", "province", "radio_access_type", "application_category")

TIME_FORMAT = "%H:%M"

MAX_RESULT_ROWS = 40
MAX_STEPS = 6

#: Appended to every answer. The prompt asks for it too, but the model drops it
#: often enough that the demo cannot depend on compliance.
CAVEAT = (
    "Caveat: Data contains DP noise, cells under 10 subscribers are suppressed, "
    "and counts are subscriber-cells rather than distinct subscribers."
)


class RefusedQuery(Exception):
    """Raised when a query is malformed or its result would expose a cell
    with fewer than MIN_SUBSCRIBERS_PER_CELL subscribers."""


def _format_times(df: pd.DataFrame) -> pd.DataFrame:
    """Render datetime columns as ``HH:MM`` strings.

    Left as datetimes they serialise to epoch milliseconds, which are 13-digit
    runs — ``safety.check_text`` flags those as ``long_digit_run`` and refuses
    the next LLM call, so every time-grouped question used to die on the step
    after the tool returned.
    """
    out = df.copy()
    for column in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[column]):
            out[column] = out[column].dt.strftime(TIME_FORMAT)
    return out


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
        if pd.api.types.is_datetime64_any_dtype(df[column]):
            # The model only ever sees times as HH:MM, so it can only filter on them.
            series, wanted = df[column].dt.strftime(TIME_FORMAT), True
        else:
            series, wanted = df[column], False
        if isinstance(value, (list, tuple, set)):
            values = [str(v) for v in value] if wanted else list(value)
            df = df[series.isin(values)]
        else:
            df = df[series == (str(value) if wanted else value)]

    group_by = list(group_by or [])
    unknown_group_cols = [c for c in group_by if c not in df.columns]
    if unknown_group_cols:
        raise RefusedQuery(
            f"unknown group_by column(s): {unknown_group_cols}. "
            f"Valid group_by columns: {list(GROUP_COLUMNS)}"
        )

    # The count column is always returned; asking for it as a metric is a
    # natural mistake and not worth spending a step on.
    metrics = [m for m in (metrics or []) if m not in ("n_subscribers", COUNT_COLUMN)]
    unknown_metrics = [m for m in metrics if m not in df.columns]
    if unknown_metrics:
        raise RefusedQuery(
            f"unknown metric(s): {unknown_metrics}. Use the exact column names "
            f"listed in the schema; the count column is always returned as "
            f"'{COUNT_COLUMN}' and must not be requested as a metric."
        )

    if df.empty:
        raise RefusedQuery(
            "no rows matched those filters (this is an empty selection, not a "
            "suppressed one). Check the filter values against the schema."
        )

    if group_by:
        result = df.groupby(group_by, as_index=False).agg(
            **{COUNT_COLUMN: ("n_subscribers", "sum")},
            **{metric: (metric, "mean") for metric in metrics},
        )
    else:
        row = {COUNT_COLUMN: df["n_subscribers"].sum()}
        row.update({metric: df[metric].mean() for metric in metrics})
        result = pd.DataFrame([row])

    if (result[COUNT_COLUMN] < MIN_SUBSCRIBERS_PER_CELL).any():
        raise RefusedQuery(
            f"result contains a cell with fewer than {MIN_SUBSCRIBERS_PER_CELL} subscribers"
        )
    return _format_times(result)


def describe_schema() -> str:
    """The release's real schema, as prompt text.

    Read from the parquet itself so it cannot drift from the published file.
    Without this the model guesses column names (``hour``, ``hour_of_day``)
    and burns every step of its budget on failed calls.
    """
    df = data.load_aggregate_release()
    if df is None:
        return "The aggregate release is not available; no query can be answered."

    lines = ["GROUP_BY COLUMNS (these are the only ones allowed) and their full value lists:"]
    for column in GROUP_COLUMNS:
        if column not in df.columns:
            continue
        if pd.api.types.is_datetime64_any_dtype(df[column]):
            values = sorted(df[column].dt.strftime(TIME_FORMAT).unique())
        else:
            values = sorted(str(v) for v in df[column].unique())
        lines.append(f"- {column}: {values}")

    metric_columns = [
        c for c in df.columns if c not in GROUP_COLUMNS and c != "n_subscribers"
    ]
    lines.append("")
    lines.append("METRIC COLUMNS (request by exact name):")
    lines.append(", ".join(metric_columns))
    lines.append("")
    lines.append(
        "UNITS: the *_GB_sum_total columns are gigabytes. http_sr_avg_* is a success "
        "rate and tcp_retrans_byte_ratio_* is a ratio. The units of tp_dl_avg_*, "
        "tp_ul_avg_*, tp_dl_filtered_avg_*, the *_rtt_* columns and "
        "http_response_time_avg_* are NOT documented in the source data — report "
        "those numbers bare, and NEVER attach a unit such as Mbps, Gbps or ms to them."
    )
    return "\n".join(lines)


def _system_prompt() -> str:
    return (
        "You are an AI Analyst for Elisa's anonymised network data. You answer only "
        "from the published aggregate release, which you reach through ONE tool.\n\n"
        "To call the tool, reply with EXACTLY this JSON and nothing else:\n"
        '{"action": "query_aggregate", "filters": {"radio_access_type": "5G"}, '
        '"group_by": ["radio_access_type"], "metrics": ["tp_dl_avg_median"]}\n\n'
        "When you have the answer, reply with:\n"
        '{"answer": "Your short answer here.", "plot_type": "bar", "x_axis": "col1", '
        '"y_axis": "col2"}\n\n'
        'The "plot_type", "x_axis" and "y_axis" fields are OPTIONAL. Include them only '
        "if the user asked for a plot AND the axes are columns of the table your LAST "
        'query returned. Use "bar", "line", "point" or "arc" for plot_type.\n\n'
        "You may call the tool more than once before answering — compare, drill down, "
        "or retry with corrected arguments if a call is refused.\n\n"
        "SCHEMA\n"
        f"{describe_schema()}\n\n"
        "HOW TO READ THE RESULTS\n"
        f"- Every result carries '{COUNT_COLUMN}': the number of subscribers SUMMED "
        "OVER CELLS. A subscriber active in several cells is counted once per cell, so "
        "this is NOT a distinct subscriber count and must never be described as "
        '"subscribers" or as a population total. Call it "subscriber-cells".\n'
        "- Metric values are means taken across cells of an already-aggregated "
        "statistic. Say so if you report one; per-cell medians are the trustworthy "
        "figures.\n"
        "- Groups below 10 subscribers are suppressed from the release, and counts "
        "carry Laplace noise at epsilon 1.0.\n"
        '- "Undefined" is a real value in province and application_category: it means '
        "the source did not record one. Never present it as a place or an app without "
        "saying that.\n\n"
        "CRITICAL RULES\n"
        "1. End every final answer with exactly this line: 'Caveat: Data contains DP "
        "noise, cells under 10 subscribers are suppressed, and counts are "
        "subscriber-cells rather than distinct subscribers.'\n"
        "2. Output ONLY the JSON block. No markdown fences, no prose outside the JSON.\n"
        "3. Never output any sequence of 10 or more digits. Round every number to 2 "
        "decimal places.\n"
        "4. Never invent a figure you did not get from the tool, and never state a "
        "unit the schema does not give you.\n"
        "5. Describe ONLY the scope you actually queried. Each tool result is "
        "prefixed with the filters and grouping that produced it — if the filters "
        "were empty the numbers are national, so do not name a province.\n"
        "6. Do not repeat a query you have already run. Once the table you need is "
        "above, answer from it.\n"
    )


def _chart_spec(command: dict, df: pd.DataFrame | None) -> dict | None:
    """Build a Vega-Lite spec, or None if the requested axes do not exist.

    The spec is assembled here rather than taken from the model so that the
    plotted numbers are the tool's, not the model's recollection of them.
    """
    if df is None or df.empty:
        return None
    x_axis, y_axis = command.get("x_axis"), command.get("y_axis")
    plot_type = command.get("plot_type")
    if not (plot_type and x_axis and y_axis):
        return None
    if x_axis not in df.columns or y_axis not in df.columns:
        return None
    x_type = "quantitative" if pd.api.types.is_numeric_dtype(df[x_axis]) else "nominal"
    return {
        "mark": plot_type,
        "encoding": {
            "x": {"field": x_axis, "type": x_type, "sort": None},
            "y": {"field": y_axis, "type": "quantitative"},
        },
        "data": {"values": df.to_dict(orient="records")},
    }


def _llm(prompt: str, system: str, purpose: str) -> str:
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from src import safety

    return safety.llm_gateway(prompt, purpose=purpose, system=system)


def run_agent(mode: str, question: str, history: list | None = None) -> dict:
    if mode != "analyst":
        raise ValueError(f"Unknown mode {mode}")

    system = _system_prompt()

    history_text = ""
    for message in (history or [])[-4:]:
        # The page appends the live question to session_state before calling us,
        # so drop it here rather than asking it twice.
        if message["role"] == "user" and message["content"] == question:
            continue
        role = "User" if message["role"] == "user" else "Assistant"
        history_text += f"{role}: {message['content']}\n"

    prompt = f"Conversation History:\n{history_text}\nNew User Question: {question}"

    tool_calls: list[dict] = []
    last_df: pd.DataFrame | None = None
    seen: set[str] = set()

    for step in range(MAX_STEPS):
        if step == MAX_STEPS - 1 and tool_calls:
            prompt += (
                "\nThis is your final step. Reply NOW with the "
                '{"answer": "..."} JSON, using the tables above.'
            )
        try:
            response = _llm(prompt, system, purpose=f"analyst_step_{step}")
        except Exception as exc:  # noqa: BLE001 - surfaced to the user as text
            return {"answer": f"LLM Gateway Error: {exc}", "tool_calls": tool_calls}

        start, end = response.find("{"), response.rfind("}")
        if start == -1 or end == -1:
            prompt += "\nError: No JSON found in your response. Output ONLY valid JSON."
            continue
        try:
            command = json.loads(response[start : end + 1])
        except json.JSONDecodeError:
            prompt += "\nError parsing JSON from your response. Output ONLY valid JSON."
            continue

        if "answer" in command:
            text = str(command["answer"]).strip()
            if CAVEAT not in text:
                text = f"{text}\n\n{CAVEAT}"
            answer = {"answer": text, "tool_calls": tool_calls}
            chart = _chart_spec(command, last_df)
            if chart:
                answer["chart"] = chart
            return answer

        if command.get("action") != "query_aggregate":
            prompt += "\nUnknown action. Use 'query_aggregate' or answer."
            continue

        filters = command.get("filters", {})
        group_by = command.get("group_by", [])
        metrics = command.get("metrics", [])
        log = {
            "action": "query_aggregate",
            "filters": filters,
            "group_by": group_by,
            "metrics": metrics,
        }
        signature = json.dumps(log, sort_keys=True, default=str)
        if signature in seen:
            # Left to itself the model will re-run a successful query until the
            # step budget runs out and the user gets no answer at all.
            prompt += (
                "\nYou have already run that exact query and its result is above. "
                'Do not call the tool again — reply with the {"answer": "..."} JSON now.'
            )
            continue
        seen.add(signature)

        scope = (
            f"Result for filters={filters or 'none (national)'}, "
            f"group_by={group_by or 'none'}:"
        )
        try:
            df = query_aggregate(filters, group_by, metrics)
            last_df = df
            result_text = df.head(MAX_RESULT_ROWS).round(4).to_json(orient="records")
            if len(df) > MAX_RESULT_ROWS:
                result_text += f"\n({len(df)} rows total; first {MAX_RESULT_ROWS} shown.)"
            log["status"] = "success"
        except Exception as exc:  # noqa: BLE001 - fed back so the model can retry
            result_text = f"Error calling tool: {exc}"
            log["status"] = "error"
            log["error"] = str(exc)

        tool_calls.append(log)
        prompt += (
            f"\nTool Result:\n{scope}\n{result_text}\n\n"
            "If this answers the question, reply with the "
            '{"answer": "..."} JSON now. Only call the tool again if you need data '
            "you have not already retrieved."
        )

    return {
        "answer": "Max steps reached without an answer. Please try simplifying your query.",
        "tool_calls": tool_calls,
    }
