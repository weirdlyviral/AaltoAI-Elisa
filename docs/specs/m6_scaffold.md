# M6.0 — Web app scaffold

All CLAUDE.md rules apply. Branch `m6-prototype` off current main.
Goal: a runnable skeleton with four pages, a shared data layer and shared
styling, so three people can build pages in parallel without touching each
other's files. **Do NOT touch src/, config/ or outputs/** in this step.
Ask me before adding streamlit (and plotly if you want it for charts).
Page-level detail lives in docs/specs/m6.md; this spec is structure only.

## Structure
```
app/
  Home.py                          # Pipeline visualiser (owner: Aviral)
  pages/
    1_Trade-off_Explorer.py        # owner: TBD
    2_AI_Analyst.py                # owner: TBD
    3_AI_Red_Team.py               # owner: TBD
  lib/
    data.py        # the ONLY way pages read data
    theme.py       # page config, CSS, header, footer
    components.py  # reusable UI pieces
    agent.py       # stub: shared tool harness for pages 2 and 3
  assets/
    diagrams/      # SVG/HTML diagrams for Home
    styles.css
.streamlit/config.toml             # theme (light + dark friendly), no telemetry
tests/test_app.py
```
Entry point: `streamlit run app/Home.py`. Add run instructions to the README.

## The recipient rule (non-negotiable)
The app is a data RECIPIENT. It must run with SECURE_DIR unset, and it never
imports src.safety.load_raw or reads raw data. Pages never open files directly:
everything goes through app/lib/data.py, which may read only:
- outputs/*.json
- outputs/releases/aggregate.parquet
- docs/*.md (for rendering text)
Show a small persistent footer badge: "This app never accesses raw data —
it reads only the published release and evaluation reports."

## app/lib/data.py
Cached loaders (st.cache_data), each returning a dict or DataFrame, or
`None` if the file is missing (pages then show a "pending" placeholder, never crash):
- load_profile(), load_baseline_risk(), load_classification()
- load_release_stats(mode), load_transform_log(mode)
- load_risk_eval(), load_utility_eval(), load_sweep()
- load_tradeoff_grid()     # file may not exist yet
- load_aggregate_release() # DataFrame
- load_decisions()         # outputs/release_decisions.jsonl, may not exist
Plus a display-layer mapping to EDPB Guidelines 02/2026 terms, so pages never
show old names even before the underlying JSON is renamed:
- singling_out → "No Record Isolation", linkability → "No Linkage",
  inference → "No Inference"
- worst_case → "Simplified approach", realistic → "Contextual approach"
- ATTACK_CRITERION = {A1: isolation, A2: linkage, A3: inference, A4: isolation,
  A5: inference, A6: inference}
Also a `headline_numbers()` helper returning the key figures for Home
(baseline 36.3% / 99.6%, coverage, U1 headline, A6 accuracy vs bound) read
from the JSON files, never hard-coded.

Define and document here the expected schema of outputs/tradeoff_grid.json
(list of {config: {k, time_bucket, area_mode, epsilon}, metrics: {...},
criteria: {no_record_isolation, no_linkage, no_inference: pass|fail|residual},
releasable: bool}) and ship a small MOCK file at app/lib/mock_tradeoff_grid.json
(clearly labelled mock, fake numbers) so the explorer can be built before the
real grid exists. load_tradeoff_grid() falls back to the mock with a visible
"MOCK DATA" banner.

## app/lib/theme.py
setup_page(title, icon): page config (wide layout), inject assets/styles.css,
render the header (project name + one-line tagline) and the footer badge.
A small colour palette as constants: pass / fail / residual / neutral, readable
in both light and dark themes.

## app/lib/components.py
- metric_card(label, value, caption)
- criterion_badge(name, status)            # traffic light
- before_after(label, raw, record, aggregate)
- step_card(number, title, body_md, risk_md, numbers: dict)  # used by Home
- html_block(path_or_str, height)          # embeds SVG/HTML diagrams from assets/
- pending(what)                            # placeholder when data is missing

## app/lib/agent.py (stub only)
- query_aggregate(filters: dict, group_by: list, metrics: list) -> DataFrame:
  runs locally on the aggregate release; refuses (raises RefusedQuery) if any
  result cell has n_subscribers < 10. Implement this function fully (it's small
  and safety-critical); leave the LLM loop as a TODO stub with the signature
  run_agent(mode: "analyst"|"red_team", question: str) -> dict.

## Pages (placeholders only)
Each page: setup_page(...), a one-paragraph description of what it will do
(from docs/specs/m6.md), an "Owner: TBD" note, and one real element wired to
data.py so the plumbing is proven:
- Home: headline_numbers() as metric cards + a placeholder for the pipeline
  diagram (an empty assets/diagrams/pipeline.svg) + a list of the step cards
  with titles only: Collect → Classify → Transform → Release → Attack → Measure → Decide.
- Trade-off Explorer: sliders for k, time bucket, area mode, ε reading options
  from the (mock) grid; show the matched config's criteria badges.
- AI Analyst: a text box + a button that calls query_aggregate for one
  hard-coded example query and shows the table.
- AI Red Team: static description + a disabled "Run attack" button.

## Tests (tests/test_app.py)
- importing app.lib.* and each page with SECURE_DIR unset works
- no file under app/ imports load_raw or references SECURE_DIR (grep/AST test)
- query_aggregate refuses a query producing a cell with < 10 subscribers
- data.py returns None (not an exception) for a missing file
- each page renders without exceptions (streamlit.testing AppTest)
- the leak guard also scans app/ (mock grid included)

CHECK: pytest green, `streamlit run app/Home.py` loads all four pages, leak
guard clean. Commit on m6-prototype, push, and print the file ownership map
so we can split the work.
