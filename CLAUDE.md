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

## Framing
- **Headline = the aggregate release with differential privacy.** The record
  release is published alongside it as a comparison, not as the recommendation.
- **Risk is assessed relative to the defined recipient** (EDPS v SRB, relative
  approach): an Elisa product team with no raw data access and no auxiliary
  identity data. A claim that holds for that recipient is not a claim that holds
  for Elisa itself, which holds the source.
- **Never claim "fully anonymous".** Report the epsilon and the empirical attack
  rates, and say what each one does and does not cover.
- **Limitation:** anonymisation does not settle purpose limitation under
  ePrivacy. Lawful reuse is a separate question from re-identification risk.

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
  + `src/anonymise.py`. **Aggregate is the headline release**, record is published
  beside it for comparison, and **session linkage is optional** (built only with
  an explicit `--mode session`; `--mode all` = aggregate + record).
  Shared transforms: drop `msisdn`/`imsi`/`imei`/`tac`; 15-min `time_bucket`;
  `enb` -> `area` (rare cells -> `<province>_OTHER`, rest -> random tokens, map in
  memory only); rare categories -> `OTHER`; QoE winsorised at [0.01, 0.99];
  volumes top-coded at p99; all numerics to 3 significant figures.
  Record/session: k=10 on DISTINCT SUBSCRIBERS, escalating area to province before
  suppressing - 0.32% rows suppressed, 33.6% escalated, min 10 subscribers/group.
  Aggregate: ONE granularity only (no marginals or totals file), primary
  suppression below 10 subscribers/cell plus **secondary suppression** of the
  smallest survivor in any affected (time_bucket, province) slice, so a
  suppressed cell cannot be recovered by subtraction - 1,033 primary + 78
  secondary = 29.6% of cells, leaving 2,642 cells at a median of 94 subscribers.
  **DP: Laplace, epsilon 1.0, scale 1.0, seed 42** on `n_subscribers` and `n_rows`;
  epsilon, scale and caveats are recorded in `outputs/release_stats.json`.
  Sweeps: record grid (24 combinations) keeps suppression under 5% everywhere,
  worst 1.22%; aggregate grid over epsilon in {0.5, 1, 2, none} gives mean
  relative count error 3.6% / 1.8% / 0.8% / 0 with suppression unchanged
  (it is decided on true counts, so it cannot vary with epsilon).
  61 tests. Artefacts: `outputs/transform_log.json`, `outputs/release_stats.json`,
  `outputs/sweep.json`, `docs/transformations.md`.
  Two honesty caveats to carry into the pitch: the Laplace scale assumes
  sensitivity 1, which holds for `n_subscribers` but understates `n_rows`
  (one subscriber contributes many rows), so the stated epsilon is not a strict
  user-level guarantee for that column; and which cells survive suppression is
  decided on true counts, so the published cell set is not covered by epsilon.
  Area tokens are seeded (42) for reproducibility.
- [x] M1 Pipeline skeleton, validation, leak guard (Step 1-6)
- [x] M2 Anonymisation method: k-anonymity (Steps 1-3)
- [x] M2 DP counts and mode-suffixed outputs (Step 0)
- [x] M3 Risk evaluation harness (Step 1)
- [x] M3 Attacks A1-A6 (Step 2)
- [x] M3 Automated risk assessment report (Step 3)
- [ ] M3 Anonymeter (Optional, Step 4) complete. Anonymeter (Step 4) optional/TODO. Before/after table per mode.
  Added from research:
  - **l-diversity check:** per QI group in record mode, the share of groups where
    every member shares the same tethering flag (`tethering_data_GB_dl_sum` > 0)
    or the same `application_category`. k-anonymity says nothing about a group
    that is homogeneous on a sensitive attribute.
  - **Differencing test:** attempt to recover suppressed aggregate cells from the
    published ones; report the success rate. This is the empirical check on the
    secondary-suppression defence built in M2.
  - **Membership-inference-lite:** for sampled subscribers, compare the aggregate
    computed with and without them and report distinguishability at the chosen
    epsilon. This is what turns "epsilon = 1.0" into a number a reviewer can read.
- **M4 Utility metric: DONE (branch `m4-utility`, not merged).** Spec:
  `docs/specs/m4.md`. `src/utility.py` -> `outputs/utility_eval.json`,
  `docs/utility.md`. Reads published releases + raw; touches neither
  `src/anonymise.py` nor `config/release.yaml`. Wasserstein, KS and Spearman are
  implemented on numpy (scipy is not an allowed dependency).
  **HEADLINE: median `tp_dl_avg` is within 5% of raw for 99.92% of the 2,642
  published cells (target >= 90%) -> PASS.** All five U1 metrics are >= 96.8%.
  Coverage: 99.60% of raw rows, 99.99% of raw subscribers. Province ranking
  survives (Spearman 0.997 for both `tp_dl_avg` and `http_sr_avg`); the bottom-10
  worst cells are preserved 10/10 (Jaccard 1.0), 5G-only too.
  Counts at the deployed epsilon 1.0: median relative error 0.28%, p90 5.3%.
  **Two findings for M3/M5 to act on:**
  1. Top-coding at the 0.99 quantile **severely degrades 6 metrics** (mean moves
     >= 25%): `im_video_GB_sum` -100%, `http_response_time_avg` -98%,
     `im_audio_GB_sum` -99%, `tethering_data_GB_dl_sum` -89%, `data_GB_sum` -54%,
     `tp_dl_avg` -26%. On columns that are mostly zeros the p99 cap sits at or
     near zero and flattens the column outright. Medians survive, so U1 looks
     healthy while any question about totals or averages does not. The earlier
     M2 code took p99 over non-zero values only; the current code does not.
  2. Suppression is **not evenly distributed**: 2G retains 81.6% of rows against
     99.8% for 4G, and the thinnest provinces retain ~97.4% against 99.96% for
     Uusimaa ("Unavailable" retains 48.2%). Threshold methods cost the thin
     strata most, which is the known rural / rare-technology weakness.
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
