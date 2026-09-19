# Elisa Anonymisation Pipeline (AaltoAI Hackathon 2026)

A privacy-preserving anonymisation pipeline for **fabricated** telecom log data.
This repository contains the foundation: a safety layer, an aggregate profiler, a
baseline re-identification risk assessment, and LLM-assisted field classification
with a human in the loop.

> **Raw data never enters this repository.** It lives only in `$SECURE_DIR`,
> outside the working tree. Nothing here is generated without passing the leak
> guard first.

## Setup

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env    # then fill in the four values
```

`.env` variables:

| Variable | Meaning |
|---|---|
| `SECURE_DIR` | Directory holding the raw dataset and `tmp/`. Must be outside this repo. |
| `LLM_BASE_URL` | OpenAI-compatible endpoint. |
| `LLM_API_KEY` | Key for that endpoint. |
| `LLM_MODEL` | Model name. |

Optional: `DATASET_FILE` overrides the default raw filename inside `SECURE_DIR`.

## Pipeline

```bash
.venv/bin/python -m src.profile            # -> outputs/profile.json
.venv/bin/python -m src.baseline_risk      # -> outputs/baseline_risk.json
.venv/bin/python -m src.classify           # interactive review
.venv/bin/python -m src.classify --non-interactive
.venv/bin/python -m src.safety guard --dir outputs
.venv/bin/python -m src.safety wipe-tmp
.venv/bin/python -m pytest tests/
```

## Prototype app (M6)

A Streamlit "Anonymity Assessment Studio" reads only the published outputs —
never the raw dataset. Run it with `SECURE_DIR` unset (it doesn't need it):

```bash
.venv/bin/streamlit run app/Home.py
```

Pages: **Home** (pipeline walkthrough), **Trade-off Explorer** (k / time
bucket / area mode / epsilon grid), **AI Analyst**, **AI Red Team** (both
stretch goals, M6.3). See `app/lib/data.py` for the full read-only data
contract and `docs/specs/m6.md` / `docs/specs/m6_scaffold.md` for the spec.

Before deploying, regenerate `app/static/story/story_data.json` from the
approved outputs and run the leak guard. Never publish `outputs/releases/`, raw
data, `.env`, or LLM credentials.

### Full app deployment

Deploy the full Streamlit app from `app/Home.py` using Streamlit Community
Cloud or another Python-capable host. The walkthrough is embedded directly in
Streamlit, so no second provider is required. Add the values from
`.env.example` as server secrets, including `AGGREGATE_RELEASE_URL` pointing
to a private or signed URL for the approved `aggregate.parquet` release. The
aggregate release is read in memory and is never committed to this repository.

On Streamlit Community Cloud, choose `app/Home.py` as the app file and use the
repository root as the working directory. `requirements.txt` already contains
the runtime dependencies.

## Safety model

[`src/safety.py`](src/safety.py) is the only component that touches raw data or
the network.

- **`load_raw`** is the single sanctioned reader. It refuses any path outside
  `SECURE_DIR`, reads `msisdn` / `imsi` / `imei` as strings so leading zeros
  survive, and registers every distinct identifier value into an in-memory
  registry that is never written and never printed.
- **`scrub` / `check_text` / `check_file`** detect registered identifiers and
  residual runs of 10+ digits. A `Finding` records *where* a leak is, never
  *what* it is.
- **`leak_guard`** scans a directory recursively and exits non-zero on any
  finding.
- **`safe_write_json` / `safe_write_df` / `safe_write_text`** stage every write
  inside `$SECURE_DIR/tmp`, scan it, and promote it to its target only if clean.
  `safe_write_df` additionally refuses any frame carrying an identifier column.
- **`llm_gateway`** is the only network egress. It scans the prompt and system
  message *before* constructing a client, and logs every call to
  `outputs/llm_calls.jsonl` (git-ignored).
- **`@safe_main`** wraps every CLI entry point so no exception message or
  traceback can carry a raw value to the terminal.

## Dataset notes

Three properties of the shipped mock extract that shape the risk numbers:

1. The cell column ships as **`enb_id`**; `load_raw` normalises it to `enb`.
2. `time_start` is stored as **int64 epoch seconds**, not a timestamp.
3. **`tac` is constant** across all subscribers, and the extract covers a
   **single hour on one date** — so device model and date contribute no
   separating power in the baseline risk measures.

## Layout

```
src/safety.py         safety layer: loading, scrubbing, guarding, writing, LLM egress
src/profile.py        aggregate column + structure profile
src/baseline_risk.py  R1 row uniqueness, R2 trajectory uniqueness, R3 outlier exposure
src/classify.py       LLM field classification + human review
config/fields.yaml    reviewed class and treatment per field
docs/                 dataset description
outputs/              generated artefacts (all leak-guard verified)
tests/                safety-layer tests (synthetic data only)
app/                  M6 prototype: Streamlit app, recipient-only (see app/lib/data.py)
```
