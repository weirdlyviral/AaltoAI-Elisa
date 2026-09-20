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
  sensitivity 1 - BOTH FIXED IN M3: `n_rows` was dropped from the release
  entirely, the Laplace scale is now `max_cells_per_subscriber / epsilon`
  (11/1.0), and primary suppression is decided on the NOISY count so the
  published cell set is covered by epsilon too.
  Area tokens are seeded (42) for reproducibility.
- [x] M1 Pipeline skeleton, validation, leak guard (Step 1-6)
- [x] M2 Anonymisation method: k-anonymity (Steps 1-3)
- [x] M2 DP counts and mode-suffixed outputs (Step 0)
- **M3 Risk evaluation: DONE.** Spec: `docs/specs/m3.md`. `src/evaluate.py` +
  `config/evaluate.yaml` -> `outputs/risk_eval.json`, `docs/risk_assessment.md`.
  Step 0 landed in `src/anonymise.py`: contribution bounding (scale =
  `max_cells_per_subscriber`/epsilon = 11), `n_rows` dropped, noisy-threshold
  suppression, mode-suffixed outputs, non-zero p99 top-coding for volumes.
  All six attacks are MEASURED (12 tests, incl. one that parses `evaluate.py`
  with `ast` and fails any attack returning a constant):
  - **A1 singling out:** 0% of record rows unique; P(identify) = 0.025, vs 36.31%
    of subscribers exposed in raw.
  - **A2 linkability:** not runnable - no subscriber key. If rows *were*
    linkable, 4 points still single out 99.3% at area granularity, 3.8% at
    province. The defence is structural, not statistical - say so in the pitch.
  - **A3 inference:** no QI group is homogeneous on the revealing value of
    tethering / heavy-user / video. Homogeneous-on-False is common (94% for
    video) and is a far weaker disclosure. `application_category` is excluded:
    it is a QI, so homogeneity on it is 100% by construction.
  - **A4 singling out:** the weakest result. Volume is not in the QI set, so an
    attacker who also knows the target's rough data volume pushes 2.01% of rows
    below k, with 16,850 heavy-user rows among them.
  - **A5 singling out:** 0% of suppressed cells recovered - but also 0%
    undefended, because no slice in this extract ever loses exactly one cell.
    Secondary suppression costs 80 cells and is UNTESTED on this data; the
    synthetic test proves the mechanism, the extract does not.
  - **A6 inference:** membership inference falls from 100% (no noise) to 54.0%
    at epsilon 1.0, against a 73.1% theoretical ceiling.
  Anonymeter (Step 4) remains optional/TODO.
  Known gaps: the contribution bound of 11 is a p99 and is NOT enforced (no
  cells are dropped for over-contributing subscribers), and `winsorise_qoe`
  still takes its quantile over all values, so `http_response_time_avg` is
  still -98% on the mean.
- **M4 Utility metric: DONE (branch `m4-utility`, merged with M3).** Spec:
  `docs/specs/m4.md`. `src/utility.py` -> `outputs/utility_eval.json`,
  `docs/utility.md`. Wasserstein, KS and Spearman implemented on numpy.
  Re-run against the post-M3 releases:
  **HEADLINE: median `tp_dl_avg` within 5% of raw for 99.61% of the 2,772
  published cells (target >= 90%) -> PASS.** All five U1 metrics pass;
  `http_response_time_avg` is closest to the line at 91.67%.
  Coverage 99.47% of rows / 99.99% of subscribers. Province ranking holds at
  Spearman 0.958; bottom-decile worst cells overlap at Jaccard 0.99
  (tie-safe set comparison; the old 10/10 top-N claim was an artefact of a
  91-cell tie at the minimum and was replaced).
  Counts at epsilon 1.0: median relative error 7.3%, p90 116% - the real price
  of honest contribution bounding (scale 1 -> 11).
  M3's non-zero p99 fix cut severely-degraded metrics from 6 to 5 and rescued
  `im_video_GB_sum` from -100% to -14.9%.
  Suppression is still uneven: 2G keeps 82.14% of rows vs 99.72% for 4G; the
  worst province keeps 49.40%.
- **M5 Risk narrative & docs: TODO.** Risk register, row-level docs,
  data-handling statement, limitations.
- **M6 Bonus prototype: only if M0–M5 green.** "Anonymity Assessment Studio" on
  anonymised data (EDPB Guidelines 02/2026 framing). Specs: `docs/specs/m6.md`,
  `docs/specs/m6_scaffold.md`. **M6.0 scaffold started early on branch
  `m6-prototype` (structure only, in parallel with M5), not yet merged.**
  `app/` — Home + three page placeholders, `app/lib/{data,theme,components,agent}.py`,
  `query_aggregate` fully implemented (refuses cells with <10 subscribers),
  mock trade-off grid at `app/lib/mock_tradeoff_grid.json`. The app is a
  RECIPIENT: no import of the raw-data reader, no reference to the raw-data
  secure-storage location anywhere under `app/` (tested). `tests/test_app.py`
  (11 tests): imports clean, leak guard scans `app/` clean, mock-grid
  fallback, refusal test, all four pages render via `streamlit.testing`.
  Page content (6.1–6.3) not built yet.
- **M6 integration (branch `m6-integrate`): robi's Trade-off Explorer and AI
  Analyst merged in.** Taken from `origin/robi`: `app/pages/1_Trade-off_Explorer.py`
  (altair scatter over the 48-config grid, click-to-select), `2_AI_Analyst.py`
  (chat UI), `app/lib/agent.py` (`run_agent` analyst loop via `safety.llm_gateway`,
  max 6 steps; `query_aggregate` unchanged), `outputs/tradeoff_grid.json`,
  `generate_tradeoff*.py`, `docs/privacy_thresholds.md`.
  NOT taken: robi's `src/`, `outputs/risk_eval.json`, `outputs/utility_eval.json`,
  `config/` and notebooks - that branch predates the U3 fix and the verdict rules
  and would have reverted them.
  Fixed on the way in: the explorer crashed on load (Streamlit refuses selections
  on layered altair charts); the grid failed the leak guard on unrounded float
  repr; the mock grid used different metric keys from the real one.
  **Open: two rule systems for "releasable"** - `docs/privacy_thresholds.md`
  (fixed ceilings, drives the explorer) vs `app/lib/verdicts.py` (relative to 1/k
  and the DP bound, drives the scoreboard). Cross-referenced, not reconciled.
- **M6 AI Analyst hardened (branch `m6-analyst-fixes`): DONE.** Verified live against
  the Verda endpoint, then fixed what the verification broke on. `time_bucket` left
  the tool as epoch millis, so `safety.check_text` flagged `long_digit_run` and
  refused the NEXT gateway call - every time-grouped question died with "LLM Gateway
  Error"; datetimes are now `HH:MM` strings. The system prompt listed 5 metrics and
  no group_by columns, so the model guessed `hour`/`hour_of_day` and invented units
  ("0.05 Gbps" then "51.6 Mbps" for the same field); it is now built by
  `agent.describe_schema()` from the parquet itself, and told that throughput/RTT/
  HTTP-response-time units are UNDOCUMENTED and must be reported bare. The summed
  count is renamed `n_subscriber_cells` (grouping by `time_bucket` summed to 712,513
  against 199,195 actual subscribers) and the model is told never to call it a
  headcount. Unknown metrics are refused instead of silently dropped; an empty
  selection is distinguished from a suppressed one; `n_subscribers`/`n_subscriber_cells`
  as a metric no longer raises `TypeError`. Charts are dropped unless the axes are
  columns of the last result (the old code plotted an unrelated query under a
  "cannot plot" answer). Repeated identical calls are refused and the final step
  forces an answer (softening the old "answer now" push made it loop 6 times);
  the caveat line is appended in code rather than trusted to the model; tool results
  are prefixed with the filters that produced them (it was claiming "in Uusimaa"
  for national queries). `importlib.reload` dev hacks removed from the page. 26 new
  tests in `tests/test_app.py` (159 pass; the pre-existing red
  `test_no_colour_literal_outside_tokens_css` is untouched and also fails on main).
  Still open: no offline fallback, so a Verda outage during the pitch shows a bare
  gateway error.
- **M6 red team dropped for time:** the GDPR RULES and COMPLY story layer is the
  review focus; no red-team page or release artefacts are carried on this branch.
- **M6 UI polish (branch `m6-ui-polish`, off main): DONE, not pushed.** Fixes to the
  deployed app. The chrome bugs were all dead selectors: `collapsedControl` and
  `stAppViewBlockContainer` do not exist in Streamlit 1.39 (they are
  `stSidebarCollapsedControl` and `stMainBlockContainer`), so the stray chevron and
  the 6rem header band were never actually being hidden. The walkthrough was not
  broken but mis-sized - a vh-based sticky layout inside a fixed 1500px iframe centres
  its content below the fold; the iframe is now forced to 100vh with the parent's
  scroll locked. Fonts never loaded when hosted (srcs pointed at 127.0.0.1:8765, and
  `embedded_story` stripped the story's @import outright), so `theme.font_face_css()`
  now inlines both woff2 as data URIs for the pages AND the iframe. Story copy cut
  from 26 beats to 15, bodies to 2-3 sentences, `lens` dropped everywhere and the
  technique `chip` kept. Home restyled in place (number-led stat cards, real CTA
  button, nav active-state). Known pre-existing red test, untouched by this branch:
  `test_no_colour_literal_outside_tokens_css` fails on two hard-coded colours in
  `app/static/story/story.css` (also fails on main).
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
