"""Shared tool harness for the AI Analyst and AI Red Team pages (M6.3).

``query_aggregate`` is the only data tool either agent gets: it runs pandas
locally on the published aggregate release and refuses to return any cell
with fewer than ``MIN_SUBSCRIBERS_PER_CELL`` subscribers. No arbitrary code
execution, and no path to raw data — it only ever touches what
``data.load_aggregate_release`` hands it.
"""
from __future__ import annotations

import json
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


def run_agent(mode: str, question: str, history: list = None) -> dict:
    if mode == "analyst":
        system = (
            "You are an AI Analyst for Elisa's network data. "
            "You have ONE tool: query_aggregate. You can call it by responding with EXACTLY this JSON format:\n"
            '{"action": "query_aggregate", "filters": {"province": "Uusimaa"}, "group_by": ["radio_access_type"], "metrics": ["tp_dl_avg_median"]}\n\n'
            "Available metrics: tp_dl_avg_median, tp_ul_avg_median, cont_rtt_radio_avg_median, http_response_time_avg_median, http_sr_avg_median.\n"
            "If you have the answer, reply with:\n"
            '{"answer": "Your short answer here."}\n\n'
            "CRITICAL RULES:\n"
            "1. You MUST include this exact caveat line in your final answer: 'Caveat: Data contains DP noise, cells under 10 subscribers are suppressed, and means are not supported for QoE metrics.'\n"
            "2. Output ONLY the JSON block, no markdown formatting like ```json ... ```."
        )
        history_text = ""
        if history:
            for msg in history[-4:]:  # last 4 messages to save context
                role = "User" if msg["role"] == "user" else "Assistant"
                history_text += f"{role}: {msg['content']}\n"
        prompt = f"Conversation History:\n{history_text}\nNew User Question: {question}" 
        
        tool_calls = []
        last_df = None
        for step in range(6):
            try:
                import sys
                from pathlib import Path
                repo_root = Path(__file__).resolve().parents[2]
                if str(repo_root) not in sys.path:
                    sys.path.insert(0, str(repo_root))
                
                from src import safety
                response = safety.llm_gateway(prompt, purpose=f"analyst_step_{step}", system=system)
            except Exception as e:
                return {"answer": f"LLM Gateway Error: {e}", "tool_calls": tool_calls}
                
            try:
                start = response.find("{")
                end = response.rfind("}")
                if start == -1 or end == -1:
                    prompt += "\nError: No JSON found in your response. Output ONLY valid JSON."
                    continue
                cmd = json.loads(response[start:end+1])
            except Exception:
                prompt += "\nError parsing JSON from your response. Output ONLY valid JSON."
                continue
                
            if "answer" in cmd:
                ans = {"answer": cmd["answer"], "tool_calls": tool_calls}
                if "chart" in cmd and isinstance(cmd["chart"], dict) and last_df is not None:
                    chart_spec = cmd["chart"]
                    chart_spec["data"] = {"values": last_df.to_dict(orient="records")}
                    ans["chart"] = chart_spec
                return ans
            elif cmd.get("action") == "query_aggregate":
                filters = cmd.get("filters", {})
                group_by = cmd.get("group_by", [])
                metrics = cmd.get("metrics", [])
                
                tool_call_log = {"action": "query_aggregate", "filters": filters, "group_by": group_by, "metrics": metrics}
                try:
                    df = query_aggregate(filters, group_by, metrics)
                    last_df = df
                    result_str = df.head(20).round(4).to_json(orient="records")
                    tool_call_log["status"] = "success"
                except Exception as e:
                    result_str = f"Error calling tool: {e}"
                    tool_call_log["status"] = "error"
                    tool_call_log["error"] = str(e)
                
                tool_calls.append(tool_call_log)
                prompt += f"\nTool Result:\n{result_str}\n\nNow, provide the final answer using the {{\"answer\": \"...\"}} format."
            else:
                prompt += "\nUnknown action. Use 'query_aggregate' or 'answer'."
                
        return {"answer": "Max steps reached without an answer. Please try simplifying your query.", "tool_calls": tool_calls}

    elif mode == "red_team":
        return {
            "answer": "Red team mode is being provisioned.",
            "strategy": [],
            "success_rate": 0.0
        }
    else:
        raise ValueError(f"Unknown mode {mode}")
