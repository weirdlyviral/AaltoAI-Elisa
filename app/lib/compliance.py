"""Single source for the COMPLY chapter and its offline evidence matrix."""
from __future__ import annotations

from pathlib import Path


EVIDENCE_ROOT = Path(__file__).resolve().parents[2]


def rows(values: dict | None = None) -> list[dict]:
    values = values or {}
    unique_pct = values.get("baseline_unique_pct", "99.6")
    cap_status = values.get("contribution_cap_status", "not enforced")
    return [
        {
            "requirement": "Pseudonymisation is not enough (GDPR Recital 26)",
            "control": f"Identifiers dropped AND attributes generalised; {unique_pct}% remained unique after ID removal",
            "evidence_tag": "MEASURED",
            "evidence": ["outputs/baseline_risk.json"],
        },
        {
            "requirement": "Data minimisation (Art. 5(1)(c))",
            "control": "Only the 4 grouping dimensions + QoE and volume fields; device code, cell IDs and row counts removed",
            "evidence_tag": "DOCUMENTED",
            "evidence": ["docs/transformations.md"],
        },
        {
            "requirement": "Location data (917/2014)",
            "control": "Cell IDs never published; province level only",
            "evidence_tag": "DOCUMENTED",
            "evidence": ["docs/transformations_aggregate.md"],
        },
        {
            "requirement": "The three criteria, both approaches (EDPB 02/2026)",
            "control": "Scoreboard: 3/3, 1 named residual",
            "evidence_tag": "MEASURED",
            "evidence": ["outputs/risk_eval.json", "app/lib/verdicts.py"],
        },
        {
            "requirement": "Every individual, not the average (EDPB para 36)",
            "control": f"k counted on distinct subscribers, worst-off reported, contribution cap {cap_status}",
            "evidence_tag": "MEASURED",
            "evidence": ["outputs/release_stats_aggregate.json"],
        },
        {
            "requirement": "Anonymisation is itself processing (EDPB para 38)",
            "control": "Raw data only in a secure folder; the app never reads it; the LLM never saw a row; every LLM call audited",
            "evidence_tag": "DOCUMENTED",
            "evidence": ["outputs/llm_calls.jsonl", "src/safety.py"],
        },
        {
            "requirement": "Honest labelling (EDPB para 40)",
            "control": "Never 'fully anonymous'; residual risks named",
            "evidence_tag": "DOCUMENTED",
            "evidence": ["docs/risk_assessment.md"],
        },
        {
            "requirement": "Documentation retained (EDPB para 41)",
            "control": "Row-level transformation docs, decision log",
            "evidence_tag": "DOCUMENTED",
            "evidence": ["docs/transformations.md", "outputs/release_decisions.jsonl"],
        },
        {
            "requirement": "Humans decide (responsible AI)",
            "control": "Mistral proposes field classes, a human approves with logged overrides; release approval in the Trade-off Explorer",
            "evidence_tag": "DOCUMENTED",
            "evidence": ["outputs/classification.json"],
        },
        {
            "requirement": "Re-assess over time (EDPB para 35)",
            "control": "Reproducible pipeline + tests; re-run as data and techniques change",
            "evidence_tag": "DOCUMENTED",
            "evidence": ["tests/"],
        },
    ]


def markdown(values: dict | None = None) -> str:
    lines = [
        "# Compliance matrix",
        "",
        "Generated from `app/lib/compliance.py`; the COMPLY chapter uses the same rows.",
        "",
        "| Requirement | Our control | Evidence |",
        "| --- | --- | --- |",
    ]
    for row in rows(values):
        evidence = ", ".join(f"`{path}`" for path in row["evidence"])
        lines.append(f"| {row['requirement']} | {row['control']} | **{row['evidence_tag']}** · {evidence} |")
    lines.extend(
        [
            "",
            "| **Elisa's call** | The legal basis for running the anonymisation, and whether network-quality analytics fits the permitted purposes. We provide the evidence; the lawful-basis decision is the controller's. | **DECISION** · Elisa legal team |",
            "",
        ]
    )
    return "\n".join(lines)