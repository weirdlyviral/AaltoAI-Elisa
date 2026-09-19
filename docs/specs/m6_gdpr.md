# M6 — Regulation layer in the story (replaces the red team)

All CLAUDE.md rules apply. Branch m6-prototype. Use the story's existing design
system (tokens, MEASURED/ILLUSTRATIVE tags, legibility sizes, presenter mode).

## 0. Remove the red team cleanly
- Delete app/pages/3_AI_Red_Team.py and its Home tool card; remove any links to
  it (story step 23, nav). Do NOT merge src/redteam.py or redteam_runs.json to
  main. Leave them uncommitted, or revert them on this branch.
- Home tools row: Trade-off Explorer + AI Analyst only.
- Update CLAUDE.md Status: red team dropped (time), rationale in one line.

## 1. New chapter "RULES" at the start (after the title card, before Collect)
Add "RULES" as the first pill in the progress bar. Two sub-steps.

1a. **"The rules this data lives under."** The graphic shows three cards
  sliding in one at a time (one change per sub-step):
  - GDPR: pseudonymised data is still personal data (Recital 26); purpose
    limitation (Art. 5(1)(b)); data minimisation (Art. 5(1)(c)); truly
    anonymous data falls outside GDPR (Recital 26).
  - Finnish Act on Electronic Communications Services (917/2014), as summarised
    in Elisa's brief: traffic data only for listed purposes (billing, technical
    development, network security, fraud prevention, marketing with consent);
    location data beyond what transmission needs requires consent or
    anonymisation.
  - EDPB Guidelines 02/2026 on Anonymisation (adopted 7 July 2026): three
    criteria, assessed under a contextual and a simplified approach.
  Text (70–110 words): Elisa's data was collected to run the network, not for
  product analytics. Removing the phone number doesn't change its legal status;
  only genuine anonymisation does. Do NOT cite section numbers of 917/2014
  (only what Elisa's brief states).

1b. **"What passing means."** The cards collapse into three large tiles:
  No Record Isolation · No Linkage · No Inference, each with a one-line
  plain-language question ("Can anyone be picked out?", "Can records be joined
  to someone?", "Can something be learned about a specific person?"). Quote
  Elisa's challenge text: "Can you clearly demonstrate resistance to isolation,
  linkage and inference risks?" These tiles reappear in the Attack scoreboard,
  so reuse the same component.

## 2. "Law lens" on every step
Replace the "EDPB lens:" line with a "Law lens:" chip naming the rule the step
answers. Use these mappings, and leave a step without one rather than invent:
- Collect: GDPR Art. 5(1)(b) purpose limitation; 917/2014 traffic-data purposes
- Strip: GDPR Recital 26 (pseudonymised ≠ anonymous); EDPB 02/2026 para 50
  (simple cases)
- Four points (step 8): EDPB No Linkage (para 60) / No Record Isolation (para 55)
- Blur place/time: GDPR Art. 5(1)(c) minimisation; 917/2014 location data
  published only at province level
- Group/suppress: EDPB para 55 (No Record Isolation); para 36 (protection must
  hold for ALL individuals, hence worst-off reporting)
- Publish/noise: EDPB para 67, 71b (No Inference; with/without-individual test),
  para 76 (aggregate differencing)
- Attack scoreboard: EDPB paras 45–49 (contextual vs simplified), para 97
  (compiling results)
- Measure: GDPR Art. 5(1)(c): only data needed for the stated purpose is kept useful

## 3. New chapter "COMPLY" (after Measure, before Decide)
Add "COMPLY" to the progress bar. Headline: "How we comply — and what stays
Elisa's call". Graphic: a checklist table, with rows ticking in one by one
(staggered). Columns: Requirement | Our control | Evidence (tag + file).
Rows:
1. Pseudonymisation is not enough (GDPR Recital 26) → identifiers dropped AND
   attributes generalised; we measured 99.6% still unique after ID removal →
   MEASURED · baseline_risk.json
2. Data minimisation (Art. 5(1)(c)) → only the 4 grouping dimensions + QoE and
   volume fields; device code, cell IDs and row counts removed → DOCUMENTED ·
   transformations.md
3. Location data (917/2014) → cell IDs never published; province level only →
   DOCUMENTED · release schema
4. The three criteria, both approaches (EDPB 02/2026) → scoreboard: 3/3, 1 named
   residual → MEASURED · risk_eval.json + verdicts.py
5. Every individual, not the average (EDPB para 36) → k counted on distinct
   subscribers, worst-off reported, contribution cap → MEASURED (state whether
   the cap is enforced, reading it from release_stats; don't assume)
6. Anonymisation is itself processing (EDPB para 38) → raw data only in a
   secure folder; the app never reads it; the LLM never saw a row; every LLM
   call audited → DOCUMENTED · llm_calls.jsonl, safety.py
7. Honest labelling (EDPB para 40) → never "fully anonymous"; residual risks
   named → DOCUMENTED · risk_assessment.md
8. Documentation retained (EDPB para 41) → row-level transformation docs,
   decision log → DOCUMENTED · transformations.md, release_decisions.jsonl
9. Humans decide (responsible AI) → Mistral proposes field classes, a human
   approves with logged overrides; release approval in the Trade-off Explorer →
   DOCUMENTED · classification.json
10. Re-assess over time (EDPB para 35) → reproducible pipeline + tests; re-run
    as data and techniques change → DOCUMENTED · tests/
Final row, amber (not a tick): **Elisa's call** — the legal basis for running
the anonymisation, and whether network-quality analytics fits the permitted
purposes (likely "technical development", to be confirmed by Elisa's legal
team). We provide the evidence; the lawful-basis decision is the controller's.
Stat block: "10 / 10 controls evidenced · 1 decision for Elisa".
Every "MEASURED" figure comes from story_data.json; add any missing keys in
export_story.py.

## 4. Presenter mode
?pitch=1 path: add 1b (what passing means) and the COMPLY checklist. New path:
title → 1b → step 8 → 13 → 15 → scoreboard → utility → COMPLY → Decide.

## 5. Docs
Add docs/compliance_matrix.md generated from the same data as the COMPLY table
(one source: app/lib/compliance.py), so the judges can read it offline.

## Tests
- compliance rows render from compliance.py; every evidence file referenced exists
- every MEASURED number in the new chapters is present in story_data.json
- no red-team page or links remain (grep test)
- leak guard clean; app renders with SECURE_DIR unset

CHECK: screenshot the RULES sub-steps, a step with a Law lens chip, and COMPLY at
1280×720 into the story_shots folder; 0 console errors; commit after my review.
