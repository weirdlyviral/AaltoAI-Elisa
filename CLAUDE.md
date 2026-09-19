# AaltoAI Hackathon — Elisa Challenge: Anonymising Service-Related Data

## What we're building
A privacy-preserving transformation pipeline for fabricated, row-level telecom
network data, plus honest evidence of how much re-identification risk remains.

Elisa's ask (confirmed with their team): **the method and a detailed account of
the risks are the deliverable.** There is no foolproof solution; explaining
residual risk is part of the final presentation. A prototype use case is a bonus.

The final pitch must answer:
1. Dataset overview: which fields are personal, quasi-identifying or non-identifying
2. Anonymisation approach: what we applied to each field and why it works
3. Linkability decision: how much linkage we preserved, and why
4. Re-identification risk assessment: identification, singling-out and linkage tests, and what remains
5. Data utility metric: at least one measurable baseline → target
6. Documentation: row-level explanation of every transformation, assumptions and limitations

Hard rule from the brief: source identifiers must not appear in the final
dataset, exported artefacts, debug logs, screenshots or demo materials.

Deadline: Sunday 11:00 Helsinki time (aim to submit by 10:30).

## Team and tooling
Two people. Aviral builds the pipeline; teammate owns the risk register and pitch.
Coding assistant: Claude Code. In-pipeline LLM: Mistral Large 3 on a
Verda-hosted (Finland) OpenAI-compatible endpoint, model
`mistralai/Mistral-Large-3-675B-Instruct-2512-NVFP4`.
Config in `.env`: `SECURE_DIR`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`.

## NON-NEGOTIABLE SAFETY RULES
Apply to all code AND to your own actions in this repo.
- Raw data lives ONLY in `$SECURE_DIR`, outside this repo. Temp files in `$SECURE_DIR/tmp`.
- **Never** read, cat, head, tail, grep or open the raw data file. **Never**
  print dataframe rows (`.head()`, `.sample()`, `.iloc`, printing a df) or
  values of identifier columns. Debug with aggregate statistics or `outputs/profile.json`.
- Never open, read or print files in `outputs/releases/` row by row either;
  use aggregates only.
- Anything written outside `SECURE_DIR` goes through `safety.safe_write_json` /
  `safety.safe_write_df`. Every CLI entry point is wrapped with `@safety.safe_main`.
- Run scripts via their CLI so errors are scrubbed by `safe_main`.
- No LLM (including you) ever sees a raw row: only schema, aggregate stats,
  scrubbed errors and metric outputs.
- Identifier columns: `msisdn`, `imsi`, `imei` (read as str). Derived: `tac` = first 8 chars of `imei`.
- Deterministic: seed 42. Python 3.11. Dependencies: pandas, numpy, pyarrow,
  pyyaml, openai, python-dotenv, pytest. Ask before adding anything else.
- `outputs/releases/` is gitignored: released data never goes to git, only
  JSON/markdown reports. Never commit data or `.env`.
- Run `python -m src.safety guard --dir outputs` before every commit.

## Dataset
22 columns: time_start, msisdn, imsi, imei, tp_dl_avg, tp_ul_avg,
tp_dl_filtered_avg, cont_rtt_radio_avg, cont_rtt_internet_avg,
initial_rtt_radio_avg, tcp_retrans_byte_ratio_downlink_avg,
tcp_retrans_byte_ratio_uplink_avg, http_response_time_avg, http_sr_avg,
data_GB_sum, im_video_GB_sum, im_audio_GB_sum, tethering_data_GB_dl_sum,
radio_access_type, province, application_category, enb.
Field descriptions: `docs/dataset_description.txt`.

Quirks that shape everything:
- **Single hour on one date.** No multi-day linkage exists. Linkability choice
  = no linkage vs session-level (within the hour) vs aggregates only.
- **`tac` is constant** across all 199,195 subscribers: device model adds no
  risk *here*.
- Near-zero date/device risk is an artefact of this extract, not of our method.
  Limitation to state: longitudinal and device-based risks are untested.
- **Location (`enb`) + time is the dominant quasi-identifier.**

## Baseline risk ("before" numbers, outputs/baseline_risk.json)
- QI set D (time_start + enb + radio_access_type + application_category + tac):
  **36% of subscribers** own at least one unique row.
- **4 known (enb, hour) points uniquely identify 99.6%** of sampled subscribers
  (quote as "among subscribers with ≥4 distinct cell visits in the hour").

## Status
- **M0 Safe setup: DONE.** `src/safety.py` (load_raw, scrub, check_text/check_file,
  leak_guard, safe_main, safe writers, llm_gateway with pre-send identifier check
  and `outputs/llm_calls.jsonl` audit log, wipe_secure_tmp). 29 tests, guard clean.
  `check_file` also scans `.ipynb` structurally (cell sources and stored outputs,
  skipping base64 image payloads), so a committed notebook cannot smuggle rows out.
- **M1 Profile & classify: DONE.** `outputs/profile.json`, `outputs/baseline_risk.json`,
  `outputs/classification.json`, `config/fields.yaml`. Mistral proposed classes
  from profile stats only; human review with logged overrides.
- **M2 Anonymisation method: DONE.** Spec: `docs/specs/m2.md`. `config/release.yaml`
  + `src/anonymise.py` produce three releases into `outputs/releases/` (gitignored):
  **record** (no link), **session** (`session_id` under an ephemeral HMAC key
  destroyed after use) and **aggregate** (per bucket x province x RAT x app).
  Transforms: drop `msisdn`/`imsi`/`imei`/`tac`; 15-min `time_bucket`; `enb` ->
  `area` (rare cells -> `<province>_OTHER`, rest -> random tokens, map in memory
  only); rare categories -> `OTHER`; QoE winsorised at [0.01, 0.99]; volumes
  top-coded at p99; all numerics to 3 significant figures; k=10 on DISTINCT
  SUBSCRIBERS with escalation to province before suppression.
  At k=10 / 15-min / tokenised: **0.32% rows suppressed, 33.6% escalated,
  min 10 distinct subscribers per QI group**; aggregate suppresses 27.5% of cells.
  23 tests in `tests/test_anonymise.py`; `outputs/transform_log.json`,
  `outputs/release_stats.json`, `outputs/sweep.json`, `docs/transformations.md`.
  Sweep (24 combinations, record mode): **every combination keeps suppression
  under 5%** - the worst is 1.22% (native bucket, k=20). Bucket width buys more
  than k does; `province` area_mode makes escalation a no-op.
  Known limitation: area tokens are seeded (42) for reproducibility, so anyone
  holding both the raw extract and this code can rebuild the map - tokenisation
  protects an external recipient, not Elisa as the source holder.
- **M3 Risk evaluation: TODO.** Re-run baseline attacks on each release,
  plus Anonymeter singling-out / linkability / inference. Before/after table per mode.
- **M4 Utility metric: TODO.** e.g. median download throughput per province ×
  access type × app category within 5% of raw for ≥90% of groups.
- **M5 Risk narrative & docs: TODO.** Risk register, row-level docs,
  data-handling statement, limitations.
- **M6 Bonus prototype: only if M0–M5 green.** "Service quality explorer" on anonymised data.
- **M7 Pitch & submit.**

Update this Status section whenever a milestone changes state.

## Residual risks for the write-up
Location–time trajectories; outliers (heavy users, tethering); rare attribute
combinations; homogeneity within k-anonymous groups; linkage window; key
management (a surviving hash key = pseudonymised, not anonymous); differencing
across releases; insider/auxiliary data (Elisa holds the source); fabricated
data may not transfer to real distributions; untested longitudinal and device
risks; what the LLMs saw and did not see.

## Cut order if behind
1. Bonus prototype (M6)  2. Session-linkage mode  3. Anonymeter (keep custom attacks)
Never cut: leak guard, risk register, utility metric.
