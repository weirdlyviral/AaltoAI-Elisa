# Compliance matrix

Generated from `app/lib/compliance.py`; the COMPLY chapter uses the same rows.

| Requirement | Our control | Evidence |
| --- | --- | --- |
| Pseudonymisation is not enough (GDPR Recital 26) | Identifiers dropped AND attributes generalised; 99.6% remained unique after ID removal | **MEASURED** · `outputs/baseline_risk.json` |
| Data minimisation (Art. 5(1)(c)) | Only the 4 grouping dimensions + QoE and volume fields; device code, cell IDs and row counts removed | **DOCUMENTED** · `docs/transformations.md` |
| Location data (917/2014) | Cell IDs never published; province level only | **DOCUMENTED** · `docs/transformations_aggregate.md` |
| The three criteria, both approaches (EDPB 02/2026) | Scoreboard: 3/3, 1 named residual | **MEASURED** · `outputs/risk_eval.json`, `app/lib/verdicts.py` |
| Every individual, not the average (EDPB para 36) | k counted on distinct subscribers, worst-off reported, contribution cap not enforced | **MEASURED** · `outputs/release_stats_aggregate.json` |
| Anonymisation is itself processing (EDPB para 38) | Raw data only in a secure folder; the app never reads it; the LLM never saw a row; every LLM call audited | **DOCUMENTED** · `outputs/llm_calls.jsonl`, `src/safety.py` |
| Honest labelling (EDPB para 40) | Never 'fully anonymous'; residual risks named | **DOCUMENTED** · `docs/risk_assessment.md` |
| Documentation retained (EDPB para 41) | Row-level transformation docs, decision log | **DOCUMENTED** · `docs/transformations.md`, `outputs/release_decisions.jsonl` |
| Humans decide (responsible AI) | Mistral proposes field classes, a human approves with logged overrides; release approval in the Trade-off Explorer | **DOCUMENTED** · `outputs/classification.json` |
| Re-assess over time (EDPB para 35) | Reproducible pipeline + tests; re-run as data and techniques change | **DOCUMENTED** · `tests/` |

| **Elisa's call** | The legal basis for running the anonymisation, and whether network-quality analytics fits the permitted purposes. We provide the evidence; the lawful-basis decision is the controller's. | **DECISION** · Elisa legal team |
