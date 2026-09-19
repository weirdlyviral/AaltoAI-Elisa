# Pitch guide — Elisa anonymisation challenge

A study guide for presenting and defending this solution. Written for an
engineer who is not a privacy specialist. Every number here comes from a file in
this repo; the source is named so you can check it under questioning.

**Status.** All milestones through M4 are complete and merged. Every attack in
section 6 was executed, not asserted.

---

## 1. The problem

Elisa holds row-level mobile network performance data. Each row is one
subscriber's traffic, for one application category, in one cell, during one
10-minute window — and it carries three direct identifiers: `msisdn` (the phone
number), `imsi` (the SIM) and `imei` (the handset). Even with those removed, the
rows still say **where a person was and when**, which is enough to pick an
individual out of a crowd. Elisa's product teams want to use this data to find
where service quality is bad; they should not need to know who anyone is to do
that.

Elisa's ask, per `CLAUDE.md`, is explicitly **the method plus an honest account
of the residual risk** — not a claim of perfect anonymity. The brief adds one
hard rule: source identifiers must not appear in the final dataset, exported
artefacts, debug logs, screenshots or demo materials.

**On the law — be careful here.** This repo establishes only two legal framings,
both in the `Framing` section of `CLAUDE.md`:

- **Identifiability is relative** (the *EDPS v SRB* approach): risk is assessed
  against a *defined recipient*. Ours is an Elisa product team with no raw-data
  access and no auxiliary identity data. A claim that holds for that recipient
  does **not** hold for Elisa itself, which holds the source.
- **Anonymisation does not settle purpose limitation under ePrivacy.** Whether
  reuse is lawful is a separate question from whether re-identification is hard.

> The task brief for this guide mentioned GDPR and the Finnish Act 917/2014.
> **Neither appears anywhere in this repository.** Do not assert specific
> obligations under them in the pitch — you have no repo evidence to back it up,
> and a judge who knows the law will catch it. If asked, say: "we framed
> identifiability relatively, per EDPS v SRB, and we treat ePrivacy purpose
> limitation as an open question outside our scope." That is defensible.

---

## 2. The solution

We built a pipeline that profiles the data, gets every field classified by an
LLM and confirmed by a human, then publishes **three different releases** at
different points on the privacy/usefulness scale — an aggregate table with
differential privacy (the headline), a record-level table with k-anonymity (for
comparison), and an optional session-linked table. Everything is measured, not
asserted: we quantify the re-identification risk before anonymising, and we
quantify the utility lost afterwards. A **leak guard** stands between the
pipeline and every file it writes, so nothing containing a real identifier can
reach disk.

```mermaid
flowchart TD
    RAW[("Raw extract<br/>SECURE_DIR only<br/>1,099,340 rows")]

    RAW --> PROFILE["<b>profile</b><br/>src/profile.py<br/>aggregate stats only"]
    PROFILE --> CLASSIFY["<b>classify</b><br/>src/classify.py<br/>Mistral Large 3 proposes<br/>human confirms"]
    RAW --> BASELINE["<b>baseline risk</b><br/>src/baseline_risk.py<br/>how identifiable is raw?"]

    CLASSIFY --> FIELDS[/"config/fields.yaml<br/>class + treatment"/]
    FIELDS --> ANON["<b>anonymise</b><br/>src/anonymise.py"]
    RAW --> ANON

    ANON --> AGG[["<b>aggregate</b> release<br/>HEADLINE<br/>DP, epsilon = 1.0"]]
    ANON --> REC[["<b>record</b> release<br/>k = 10, comparison"]]
    ANON --> SES[["<b>session</b> release<br/>optional, HMAC"]]

    AGG --> EVAL["<b>evaluate attacks</b><br/>src/evaluate.py<br/>A1-A6, measured"]
    REC --> EVAL
    AGG --> UTIL["<b>utility</b><br/>src/utility.py<br/>what survived?"]
    REC --> UTIL
    BASELINE -.->|before/after| EVAL

    AGG --> GUARD{{"<b>leak guard</b><br/>src/safety.py<br/>blocks every unsafe write"}}
    REC --> GUARD
    UTIL --> GUARD
    EVAL --> GUARD
    GUARD --> OUT[/"outputs/ + docs/<br/>reports only, never raw"/]
```

The guard is not a final step bolted on — it is invoked *inside* every write, so
a bad file never exists at its destination.

---

## 3. Repo walkthrough

### `src/`

| File | Lines | What it does |
| --- | --- | --- |
| `safety.py` | 643 | The chokepoint. Loads raw data, maintains the identifier registry, scrubs text, scans files, guards every write, and is the only route to the network. |
| `profile.py` | 264 | Reads raw, writes `outputs/profile.json`. Aggregates per column; identifier columns get shape only (lengths, digit share), never values. |
| `baseline_risk.py` | 283 | Reads raw, writes `outputs/baseline_risk.json`. Measures how identifiable the data is *before* anonymisation (R1 row uniqueness, R2 trajectories, R3 outliers). |
| `classify.py` | 382 | Reads `profile.json` + `docs/dataset_description.txt` only. Asks Mistral to classify all 23 fields, walks a human through each, writes `outputs/classification.json` and `config/fields.yaml`. |
| `anonymise.py` | 1,113 | Reads raw + both configs. Applies the transforms and writes the three releases, `transform_log.json`, `release_stats.json`, `sweep.json`, `docs/transformations.md`. |
| `evaluate.py` | 914 | Reads raw, rebuilds releases in memory, runs attacks A1-A6, writes `outputs/risk_eval.json` and `docs/risk_assessment.md`. |
| `utility.py` | 752 | Reads the releases + raw. Scores what survived; writes `outputs/utility_eval.json` and `docs/utility.md`. Does not modify the anonymiser. |

### `config/`

| File | What it holds |
| --- | --- |
| `fields.yaml` | Per field: the reviewed privacy `class` and the `treatment` actually applied. 23 entries. |
| `release.yaml` | The release parameters: `k: 10`, `time_bucket_minutes: 15`, `area_mode: enb_tokenised`, `dp_epsilon: 1.0`, `max_cells_per_subscriber: 11` (the contribution bound), thresholds and rounding. |
| `evaluate.yaml` | Attack sample sizes and tolerances: 1,000 trajectory samples, 200 membership targets, 100 trials each. |

### `outputs/`

| File | Written by | Contains |
| --- | --- | --- |
| `profile.json` | `profile.py` | Column and structure aggregates. |
| `baseline_risk.json` | `baseline_risk.py` | The "before" risk numbers. |
| `classification.json` | `classify.py` | Proposed vs final class per field, reviewer, timestamps. |
| `transform_log_{mode}.json` | `anonymise.py` | Every transform with its parameters and rows affected, per mode. |
| `release_stats_{mode}.json` | `anonymise.py` | Suppression, escalation, group sizes and DP settings, per mode. |
| `risk_eval.json` | `evaluate.py` | The measured result of attacks A1-A6. |
| `sweep.json` | `anonymise.py` | 24 record-mode parameter combinations + 4 epsilon settings. |
| `utility_eval.json` | `utility.py` | U1–U5 scores. |
| `llm_calls.jsonl` | `safety.py` | Audit log of every LLM call. Git-ignored. |
| `releases/*.parquet` | `anonymise.py` | The actual released data. **Git-ignored — never committed.** |

### `docs/`

`dataset_description.txt` (one line per column, the LLM's only semantic input),
`transformations_{mode}.md`, `utility.md` and `risk_assessment.md` (all
generated, never hand-edited), `specs/m2.md`, `specs/m3.md`, `specs/m4.md`, and
this guide.

### `tests/` — 92 tests

`test_safety.py` (29), `test_anonymise.py` (32), `test_utility.py` (19),
`test_evaluate.py` (12). All build their own synthetic data with fabricated
identifiers; none touches the real extract. One test parses `evaluate.py` with
`ast` and fails any attack function that returns a constant instead of measuring
something — see section 8 for why that exists.

### Run it end to end

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # then fill SECURE_DIR and the three LLM values

.venv/bin/python -m src.profile              # -> outputs/profile.json
.venv/bin/python -m src.baseline_risk        # -> outputs/baseline_risk.json
.venv/bin/python -m src.classify             # interactive field review
.venv/bin/python -m src.anonymise --mode all # aggregate + record (session is opt-in)
.venv/bin/python -m src.anonymise --mode session   # optional, explicit
.venv/bin/python -m src.anonymise --sweep    # -> outputs/sweep.json
.venv/bin/python -m src.evaluate             # -> outputs/risk_eval.json (attacks)
.venv/bin/python -m src.utility              # -> outputs/utility_eval.json

.venv/bin/python -m pytest tests/            # 92 tests
.venv/bin/python -m src.safety guard --dir outputs   # must exit 0
.venv/bin/python -m src.safety wipe-tmp
```

---

## 4. Concepts explained

### Direct identifiers vs quasi-identifiers vs sensitive attributes

**Plain:** A *direct identifier* names someone on its own — a phone number. A
*quasi-identifier* doesn't, but combined with others it narrows down to one
person — where you were, at what time, on what network. A *sensitive attribute*
isn't identifying but is revealing if it gets attached to you.

**Example:** a number like "+358 40 123 45 67" is direct. "In Kainuu, at 16:15, on 5G" is three
quasi-identifiers that together might describe exactly one person. "Used
tethering" is sensitive — harmless until it's linked to you.

**Here:** `src/classify.py` puts all 23 fields into exactly one class;
`outputs/classification.json` records the result. **3 direct** (`msisdn`,
`imsi`, `imei`), **5 quasi** (`time_start`, `radio_access_type`, `province`,
`enb`, `tac`), **4 sensitive** (`im_video_GB_sum`, `im_audio_GB_sum`,
`tethering_data_GB_dl_sum`, `application_category`), **11 non-identifying**
(throughput, latency, retransmission and HTTP metrics).

**Why:** The class decides the treatment. Direct identifiers are dropped;
quasi-identifiers are generalised and k-checked; sensitive attributes are
top-coded.

**Weakness:** The boundary is a judgement call, not a fact. `data_GB_sum` was
classed non-identifying, yet our own baseline shows volume outliers are
distinctive (R3). Classification is a starting point, not a guarantee.

### Pseudonymisation vs anonymisation — and why hashing isn't anonymisation

**Plain:** Pseudonymisation swaps an identifier for a stand-in and the link
still exists. Anonymisation destroys the link. Hashing a phone number is
*pseudonymisation*: phone numbers come from a small, guessable space, so an
attacker hashes every candidate and matches.

**Example:** 10 million possible numbers, hash them all in seconds, compare.
Salting helps only while the salt stays secret; if the salt is stored, so is the
link.

**Here:** We proved this on our own code. An earlier version tokenised cells with
unsalted `md5(enb)[:8]`; brute-forcing the ~2,000 cell IDs recovered **1,914 of
1,914 (100%)**. After salting with an ephemeral per-run salt: **0 of 1,914**.
The current cell tokens in `anonymise.build_area` come from a seeded random
permutation whose map is held in memory and never written.

**Why:** Only the aggregate and record releases are proposed as anonymous
outputs. Any surviving key means pseudonymous, not anonymous.

**Weakness:** Cell tokens use seed 42 for reproducibility, so **anyone holding
both the raw extract and this code can rebuild the map**. That protects an
external recipient, not Elisa. Stated in `docs/transformations.md`.

### k-anonymity, counted on distinct subscribers

**Plain:** Every published combination of quasi-identifiers must describe at
least *k* different people. If a group has fewer, you can single someone out.

**Example:** With k=10, a group of "16:15, area A0042, 5G, Streaming" must
contain ≥10 distinct subscribers. Nine subscribers is too few — generalise or
drop it.

**The trap we avoided:** count *distinct subscribers*, not rows. One chatty
subscriber with 19 rows would satisfy "k=10 rows" alone while being completely
exposed. `anonymise.enforce_k_anonymity` uses `nunique` on the subscriber key,
and `tests/test_anonymise.py::test_k_counts_distinct_subscribers_not_rows`
asserts that 10 rows from 1 subscriber are all suppressed.

**Here:** QI set is `[time_bucket, area, radio_access_type,
application_category]`. Result: **min 10 distinct subscribers per group**, median
79, across 27,291 groups.

**Weakness:** k-anonymity says nothing about what's *inside* a group. If all 10
subscribers in a group used tethering, you learn that about all of them without
identifying anyone — that's the l-diversity gap below.

### Generalisation, tokenisation, suppression, primary vs secondary suppression

**Plain:**
- **Generalisation** — make a value less precise (16:17 → the 16:15 bucket; a
  specific cell → its province).
- **Tokenisation** — replace a value with a meaningless label (cell `12345678` →
  `A0042`), keeping "same/different" without the real ID.
- **Suppression** — delete what can't be made safe.
- **Secondary suppression** — after deleting one thing, delete another so the
  first can't be worked out by subtraction.

**Example:** A slice publishes cells of 40, 25 and 12 subscribers, and a fourth
cell of 6 is suppressed for being too small. If you know the slice holds 83
people, 83 − 40 − 25 − 12 = 6. You've recovered it. So we also suppress the
smallest survivor (12), leaving two unknowns and one equation.

**Here:** `anonymise.aggregate_cells`. Primary suppression removed **901** cells
whose *noisy* count fell below 10; secondary removed **80** more. Total 981 of
3,753 cells = **26.1%**. We also publish **one granularity only** — no marginals
or totals file — which is what makes the subtraction attack need outside
knowledge in the first place.

**Measured (A5):** with no noise and no secondary suppression, **0%** of
suppressed cells were recovered — because no slice in this extract ever loses
exactly one cell, so the subtraction always yields the sum of several unknowns.
Secondary suppression costs 80 cells and is **untested on this data**; the
synthetic test in `tests/test_evaluate.py` proves the mechanism works when a
lone cell *is* suppressed. Say that plainly rather than claiming a win.

**Why:** Generalise first, suppress last: suppression costs data, so it is the
fallback. The record release escalates area → province *before* dropping
anything, which is why only 0.32% of rows are lost while 33.6% are coarsened.

**Weakness:** Threshold rules always cost the thin strata most — see the 2G and
rural coverage numbers in §8.

### Winsorising and top-coding (and why we don't support means)

**Plain:** Both squash extreme values. *Winsorising* clips both ends to a
percentile; *top-coding* caps the top only. Extremes identify people — the
person using 250 GB in an hour is findable by that fact alone.

**Example:** Values 1, 2, 3, 4, 500. Top-code at the 99th percentile and 500
becomes ~4. Median is unchanged (3). **Mean falls from 102 to 2.8.**

**Here:** `anonymise.winsorise_qoe` clips QoE metrics at [0.01, 0.99];
`anonymise.top_code_volumes` caps volumes at p99; everything rounds to 3
significant figures.

**This is the biggest utility cost in the project, and M4 caught it.** Mean
shifts measured in `outputs/utility_eval.json`:

| Metric | Mean change | Note |
| --- | --- | --- |
| `http_response_time_avg` | **−98.0%** | QoE metric, 94.4% zeros — winsorising, not top-coding |
| `data_GB_sum` | −53.8% | dense but heavily skewed, so the cap still removes most mass |
| `tethering_data_GB_dl_sum` | −35.7% | was −88.8% before the fix |
| `im_audio_GB_sum` | −35.6% | was −98.6% |
| `tp_dl_avg` | −26.0% | QoE metric |
| `im_video_GB_sum` | −14.9% | **was −100%** — the column is no longer destroyed |

**Say this out loud in the pitch:** *medians survive, means do not.* The release
supports "what is typical" questions and must not be used for totals or averages
on the five metrics still flagged. On a column that is mostly zeros, a p99 cap
taken over *all* values sits at zero and destroys it — which is the bug M3 fixed
for volumes and has yet to fix for QoE metrics.

**Fix status: partially fixed.** M3 changed volume top-coding to take the p99
over **non-zero values only**. That rescued the sparse volume columns —
`im_video_GB_sum` went from −100% to −14.9%, and the severely-degraded count
dropped from 6 metrics to 5. It did **not** help two cases: QoE metrics, which
are winsorised by a separate code path that still uses the all-values quantile
(`http_response_time_avg` is still −98%), and dense-but-skewed columns like
`data_GB_sum`, where the non-zero p99 is essentially the same number. Applying
the same non-zero rule to `winsorise_qoe` is the remaining fix.

### Trajectory uniqueness — the "4 points" result

**Plain:** Where you go is a fingerprint. Knowing a few places-and-times someone
visited is usually enough to find their one matching record.

**Example:** Thousands of people pass through the city-centre cell at 16:00.
Far fewer also appear in a suburb at 16:20, fewer still in a third cell at
16:40. By the fourth, it's almost always one person.

**Here:** `src/baseline_risk.py` R2, on **raw** data. A "point" is (cell, hour):

| Points known | Subscribers uniquely identified |
| --- | --- |
| 1 | 0.0% |
| 2 | 12.7% |
| 3 | 85.8% |
| **4** | **99.6%** |

Sampled 1,000 subscribers per level at seed 42, using an inverted index and set
intersection. Quote it as: *"among subscribers with at least 4 distinct cell
visits in the hour"* — that's 159,209 of 199,195 people.

**Why it matters:** this single number justifies the whole design. It's why the
headline release has no subscriber key, and why location is generalised to
province there.

**After anonymisation (measured, A2):** this is the most important honest point
in the whole deck. The record release carries **no subscriber key**, so the
attack cannot be run — rows can't be grouped into a trajectory. But if you grant
an attacker the ability to link rows anyway, 4 known points still single out
**99.3%** of targets at area granularity. **The protection is structural, not
statistical.** At province granularity — what the defined recipient actually
sees — the same attack singles out **3.8%**, with a median of 76 candidate
subscribers remaining.

**Weakness:** measured on one hour of fabricated data. With (province, date)
instead of (cell, hour), raw uniqueness is **0% at every level** — but only
because the extract is a single date, not because provinces are safe.

### l-diversity and homogeneity

**Plain:** k-anonymity hides *which* person you are. It doesn't hide *what is
true of all of them*. If everyone in your group shares a trait, the group's
anonymity doesn't protect that trait.

**Example:** A 10-person k-anonymous group where all 10 used tethering. You
can't tell which one is Anna, but if you know Anna is in that group, you've
learned she used tethering. l-diversity requires at least *l* distinct sensitive
values per group.

**Here (measured, A3):** `evaluate.run_a3` tests three sensitive flags across all
27,291 record-release QI groups. The result is good news with a caveat:

| Attribute | Groups homogeneous | Homogeneous on the *revealing* value | l (min / median) |
| --- | --- | --- | --- |
| tethering | 10.97% | **0%** | 1 / 2 |
| heavy user | 69.06% | **0%** | 1 / 1 |
| video | 94.17% | **0%** | 1 / 1 |

**No group is uniformly `True` on any sensitive attribute**, so k-anonymity is
not disclosing a positive trait. Homogeneous groups are common but they are
homogeneous on `False` — which only tells an attacker that the target *didn't*
do something, a far weaker disclosure.

`application_category` is deliberately excluded: it is itself a
quasi-identifier, so every group holds exactly one value and testing homogeneity
on it would return 100% by construction, not a finding.

**Weakness:** l-diversity has its own gaps (it ignores how skewed the attribute
is overall), which is part of why the headline release is aggregate + DP rather
than k-anonymity alone.

### Differential privacy

**Plain:** Add carefully calibrated random noise to published numbers so that
whether any one person is in the data barely changes the answer. Unlike
k-anonymity, it's a mathematical guarantee that doesn't depend on guessing what
an attacker knows.

- **Epsilon (ε)** — the privacy budget. Lower = more noise = more privacy.
- **Laplace noise** — the noise distribution, centred on zero, scaled by
  sensitivity ÷ ε.
- **Sensitivity** — how much one person can change the answer. For "count of
  distinct subscribers", one person changes it by 1.
- **Contribution bounding** — capping how much one person can affect a result, so
  sensitivity stays low.
- **Noisy-threshold suppression** — deciding what to publish using *noisy*
  counts, so the publish/suppress decision is itself covered.

**Example:** A cell truly has 50 subscribers. With ε=1 and sensitivity 1, the
noise scale is 1, so we publish about 50 ± 1. A user can't tell from 50 vs 51
whether they're in it. At ε=0.5 the scale doubles and noise roughly doubles.

**Here:** `anonymise.apply_dp_noise`. **Laplace, ε = 1.0, seed 42**, applied to
`n_subscribers` only. The scale is **11.0**, because the contribution bound is
11: a subscriber can influence up to 11 aggregate cells (the p99), so
`scale = max_cells_per_subscriber / ε`. Measured cost (`utility_eval.json` U4):
median relative error **7.3%**, p90 **116%**.

| ε | Noise scale | Median error | Mean error | Cells published |
| --- | --- | --- | --- | --- |
| 0.5 | 22.0 | 14.6% | 228% | 2,762 |
| **1.0** | **11.0** | **7.3%** | **100%** | **2,772** |
| 2.0 | 5.5 | 3.6% | 40% | 2,749 |
| none | — | 0 | 0 | 2,642 |

Those mean errors are large because cells are small: with a minimum of 10
subscribers and noise of scale 11, a small cell's count can easily double or
vanish. The **median** cell (88 subscribers) is off by 7.3%.

**What our DP covers — and what it does not:**

Covered:
1. **`n_subscribers`**, noised at scale 11/ε, with the numerator being a real
   contribution bound rather than an assumption of 1.
2. **Which cells are published**, because primary suppression is decided on the
   **noisy** count. This is why the published cell count changes with ε
   (2,772 at ε=1 versus 2,642 with no noise at all).

Not covered — know these cold:
3. **The QoE statistics carry no noise.** Medians, p10s and p90s, and the volume
   sums, are exact post-generalisation. They are protected only by the ≥10
   subscriber threshold, winsorising and top-coding.
4. **The record and session releases use no DP at all.**
5. **No budget composition.** We publish once; repeated releases would consume
   more budget and we don't track it.
6. **The contribution bound is a p99, not a maximum.** Roughly 1% of subscribers
   touch more than 11 cells, and for them the guarantee is correspondingly
   weaker. The bound is also not *enforced* — no cells are dropped for
   over-contributing subscribers, which M3's own spec had asked for.

Points 3-5 are recorded in `release_stats_aggregate.json` and
`docs/risk_assessment.md` — we wrote them down rather than hoping nobody asks.

### Differencing attacks and membership inference

**Plain:** *Differencing* — compare two overlapping published figures and
subtract to isolate one person. *Membership inference* — work out whether a
specific person is in the dataset at all, which can itself be sensitive.

**Example (differencing):** "Average salary of 10 employees" and "average salary
of the same team excluding Bob" gives you Bob's salary exactly.

**Here (measured, A5 and A6):**

*Differencing* — defended by publishing **one granularity only** plus secondary
suppression (80 extra cells). Result: **0% of suppressed cells recovered**, even
with no noise and no secondary suppression, because no slice in this extract
ever loses exactly one cell. Be precise about this: the attack fails here
because of the shape of the data, not demonstrably because of our defence.

*Membership inference* — the standard DP adversary, who knows every other
subscriber's data, sees one noisy release and runs a Laplace likelihood-ratio
test on the target's cells:

| ε | Attacker accuracy | Advantage over guessing | Theoretical ceiling |
| --- | --- | --- | --- |
| none | **100%** | +100 pts | 100% |
| 2.0 | 57.9% | +15.8 pts | 88.1% |
| **1.0** | **54.0%** | **+8.0 pts** | 73.1% |
| 0.5 | 52.1% | +4.1 pts | 62.2% |

Without noise the attacker is *always* right. At ε=1 they are barely better than
a coin flip, and comfortably inside the theoretical ceiling.

**Weakness:** the defence assumes we never publish a second, coarser table. If
anyone later publishes provincial totals from the same extract, the two together
reopen the attack.

### The Article 29 Working Party tests

**Plain:** Three questions a dataset must pass to count as anonymised:

| Test | Question | Measured answer |
| --- | --- | --- |
| **Singling out** | Can you isolate one individual's record? | **A1:** 0% of record rows are unique; expected chance of picking the target's row is 0.025 (1 in 40), against 36% of subscribers exposed in raw. **A4:** but add a 0.1 GB volume bucket to the QI and 2.0% of rows fall below k, with 16,850 heavy-user rows among them. **A5:** 0% of suppressed aggregate cells recovered by differencing. |
| **Linkability** | Can you link two records as the same person? | **A2:** no subscriber key exists in either published release, so the attack cannot be run. If linkage were somehow possible, 4 known points would still single out 99.3% at area granularity and 3.8% at province granularity. Session mode: **linkable by design**, within one release only. |
| **Inference** | Can you deduce an attribute with high confidence? | **A3:** no QI group is homogeneous on the revealing value of any sensitive attribute. **A6:** membership inference is 54.0% accurate at ε=1, against 100% with no noise. |

**Why:** These three are the standard vocabulary a privacy-literate judge will
use. Answering in their terms shows you know the framework.

**Weakness:** passing all three is not a binary state; it depends on the assumed
attacker — which is the next concept.

### The relative approach (EDPS v SRB) and our threat model

**Plain:** "Is this anonymous?" has no universal answer. It depends on *who
holds it and what else they have*. The same file can be anonymous to one party
and identifying to another.

**Here (from `CLAUDE.md`):** our defined recipient is **an Elisa product team
with no raw-data access and no auxiliary identity data**. Our claims are scoped
to that recipient.

**Say this explicitly:** *"To Elisa itself, which holds the source extract and
the subscriber database, this data is not anonymous and we don't claim it is.
Our claim is about the defined recipient."* That's an honest answer and it's
also the correct legal framing under the relative approach.

**Weakness:** if the recipient definition is wrong — say the team does have
access to a marketing database with locations — the analysis has to be redone.

### HMAC with a destroyed key (session mode)

**Plain:** HMAC is a keyed hash: without the key you can't reproduce it, which
defeats the brute-force attack that beats plain hashing. We generate a random
key, use it once, then destroy it. Rows can be linked *within* the release and
never back to a person or across releases.

**Example:** Key is 32 random bytes. `HMAC(key, msisdn)` → `a1b2c3d4-e5f6a7b8`.
Same subscriber, same ID within the file. Once the key is gone, nobody —
including us — can reverse or reproduce it.

**Here:** `anonymise.add_session_id`. The key comes from `os.urandom(32)`, is
never written, logged or returned, and is overwritten in a `finally` block.
`tests/test_anonymise.py::test_session_ids_differ_between_runs` asserts two runs
produce different IDs, which proves the key really is ephemeral.

**Why:** It's the middle option — more useful than the record release, far safer
than a persistent pseudonym.

**Weakness:** **within-release linkage is still linkage.** With a session ID you
can rebuild a subscriber's set of cells, which is exactly the 4-point attack that
identifies 99.6% of people. This is why session mode is **optional and excluded
from the default `--mode all`**, and why the aggregate release is the headline.

> One small detail worth knowing: IDs are emitted as two 8-character groups
> (`a1b2c3d4-e5f6a7b8`). 16 unbroken hex characters are all digits often enough
> that the leak guard's "10+ digits" rule would fire on a few of 200,000. The
> separator avoids that without losing entropy.

---

## 5. Safety engineering

This is a differentiator. Most teams will anonymise data; fewer will have built
a machine that makes leaking structurally hard.

| Mechanism | What it does |
| --- | --- |
| **Identifier registry** | `load_raw` records every distinct `msisdn`/`imsi`/`imei` in an in-memory set — **597,585 values**. Never written, never printed. |
| **`scrub(text)`** | Replaces any registered value with `[REDACTED]`, then any remaining run of 10+ digits with `[DIGITS]`. |
| **`check_file` / `Finding`** | Scans CSV, Parquet, JSON, JSONL, Markdown, HTML, TXT, LOG, YAML and notebooks. A `Finding` records *where* a leak is — file, column or line — and **never the matched value**. |
| **`leak_guard`** | Scans a directory recursively, prints a summary, exits non-zero on any finding. Run before every commit. |
| **Safe writers** | `safe_write_json` / `_df` / `_text` stage into `$SECURE_DIR/tmp`, scan the staged file, and promote it only if clean. `safe_write_df` also refuses any frame with an identifier column outright. |
| **`@safe_main`** | Wraps every CLI so no exception message or traceback can print a raw value. |
| **`llm_gateway`** | The only network egress. Scans the prompt *and* system message **before the client object is even constructed**, so a leaky prompt can't reach the network layer. |
| **`SECURE_DIR`** | Raw data lives outside the repo. `load_raw` refuses any path outside it. `.gitignore` covers `.env`, `*.csv`, `*.parquet` and `outputs/releases/`. |

**It works, and we can prove it.** The guard has blocked real writes four times
during development — full-precision float tails in `profile.json` (89 findings),
an untransformed volume column in a release (172,938 findings), an all-digit
hash format, and an example phone number in an early draft of this very guide.
Each was a genuine defect caught by the machine rather than by review.

### What each AI saw

| | Saw | Never saw |
| --- | --- | --- |
| **Mistral Large 3**<br/>(in-pipeline, Verda-hosted in Finland) | Column names, the one-line field descriptions, and aggregate statistics from `profile.json` | Any row. Any identifier value. Any raw record. |
| **Claude Code**<br/>(coding assistant) | The code, configs, and aggregate outputs | The raw file — never opened, read or printed it |

Every Mistral call is logged to `outputs/llm_calls.jsonl` with timestamp,
purpose, model, endpoint host, prompt, response and a SHA-256 of the prompt.
**3 calls total**: one smoke test, two field classifications. The classification
prompt was ~10,400 characters of schema and statistics.

Mistral *proposed* the classification; a human reviewed all 23 fields and the
reviewer initials are recorded in `outputs/classification.json`. The AI did not
get the final say.

---

## 6. The numbers

### The data

| Figure | Value | Source | Meaning |
| --- | --- | --- | --- |
| Rows | 1,099,340 | `profile.json` | One hour of traffic |
| Subscribers | 199,195 | `profile.json` | Distinct `msisdn` |
| Rows per subscriber | min 1, median 5, max 19 | `profile.json` | Most people appear a handful of times |
| Time span | 2027-04-30 16:00–16:50 | `profile.json` | **Single hour, one date** |
| Cells (`enb`) | 1,983 | `profile.json` | 46 have <5 subscribers |
| Provinces / app categories | 20 / 25 | `profile.json` | Grouping dimensions |
| Access types | 4G 815,112 · 5G 280,992 · **2G 3,236** | `profile.json` | 2G is rare — remember this |
| Distinct `tac` | **1** | `profile.json` | Device model is constant; adds no risk *here* |

### Baseline risk — before anonymisation

| Figure | Value | Source | Meaning |
| --- | --- | --- | --- |
| QI set D: rows unique | 8.17% | `baseline_risk.json` | 1 in 12 rows is alone in its group |
| QI set D: subscribers exposed | **36.31%** | `baseline_risk.json` | Over a third own ≥1 unique row |
| QI set A (time+cell): rows unique | 0.017% | `baseline_risk.json` | Time+cell alone is weaker than expected |
| Trajectory, 4 points | **99.6%** | `baseline_risk.json` | The headline risk number |
| Trajectory, 3 points | 85.8% | `baseline_risk.json` | Risk climbs steeply |
| Subscribers with tethering | 58.25% | `baseline_risk.json` | Relevant to l-diversity |
| Volume unique at 0.1 GB | 0.019% | `baseline_risk.json` | Low, but non-zero |

### Release stats — after anonymisation

| Figure | Value | Source | Meaning |
| --- | --- | --- | --- |
| **Aggregate** cells published | 2,772 of 3,753 | `release_stats_aggregate.json` | The headline release |
| Cells suppressed | 901 primary + 80 secondary = **26.1%** | `release_stats_aggregate.json` | The cost of the threshold |
| Min / median subscribers per cell | 10 / 88 | `release_stats_aggregate.json` | No thin cells survive |
| DP setting | Laplace, **ε = 1.0**, scale **11.0**, seed 42 | `release_stats_aggregate.json` | Scale = contribution bound (11) / ε |
| Contribution bound | 11 cells per subscriber | `config/release.yaml` | p99 of cells touched per person |
| **Record** rows published | 1,095,807 of 1,099,340 | `release_stats_record.json` | Comparison release |
| Rows suppressed / escalated | **0.32%** / 33.61% | `release_stats_record.json` | Generalise first, drop last |
| Min / median subscribers per QI group | 10 / 79 | `release_stats_record.json` | k=10 holds |
| QI groups | 27,291 | `release_stats_record.json` | |

### Parameter sweep

| Figure | Value | Source | Meaning |
| --- | --- | --- | --- |
| Record combinations tested | 24 | `sweep.json` | bucket × area mode × k |
| Worst suppression across all 24 | **1.22%** | `sweep.json` | Every combination is under 5% |
| Deployed setting | 0.32% suppressed | `sweep.json` | 15 min, tokenised, k=10 |
| ε sweep, median count error | 14.6% / 7.3% / 3.6% at ε 0.5/1/2 | `sweep.json` | The privacy-utility curve |
| ε sweep, cells published | 2,762 / 2,772 / 2,749 (2,642 unnoised) | `sweep.json` | Suppression now moves with ε |

### Utility — M4

| Figure | Value | Source | Meaning |
| --- | --- | --- | --- |
| **Headline: median `tp_dl_avg` within 5% of raw** | **99.61% of cells (target ≥90%) — PASS** | `utility_eval.json` | The number to lead with |
| Other U1 metrics | 91.7%–99.8% | `utility_eval.json` | All five pass; `http_response_time_avg` is closest to the line at 91.67% |
| U2 coverage: rows / subscribers | 99.47% / 99.99% | `utility_eval.json` | Almost everyone is represented |
| U2 coverage: **2G** | **82.14%** of rows | `utility_eval.json` | vs 99.72% for 4G — uneven |
| U2 coverage: worst province | 49.40% ("Unavailable") | `utility_eval.json` | Next worst 91.85% |
| U3 province ranking | Spearman **0.958** | `utility_eval.json` | The ranking survives |
| U3 worst cells | **Jaccard 0.99** on the bottom-decile set, ties included (268 of 271 cells shared) | `utility_eval.json` | The product question is answerable |
| U4 count error at ε=1 | median **7.3%**, p90 **116%** | `utility_eval.json` | The real price of contribution bounding |
| U5 severely degraded metrics | **5** (was 6) | `utility_eval.json` | Top-coding fix rescued `im_video_GB_sum` |

### M3 attacks — all measured

| Attack | Raw baseline | After | Source | Meaning |
| --- | --- | --- | --- | --- |
| **A1** Row uniqueness | 36.31% of subscribers exposed | **0%** of rows unique; P(identify) = **0.025** | `risk_eval.json` | Singling out by QI is gone |
| **A2** Trajectory | 99.6% at 4 points | **Not runnable** — no subscriber key. If linkable: 99.3% (area) / 3.8% (province) | `risk_eval.json` | Protection is structural, not statistical |
| **A3** Homogeneity | n/a | **0%** of groups homogeneous on the revealing value | `risk_eval.json` | No positive trait disclosed |
| **A4** Outliers | 1.00% above p99 | **2.01%** of rows below k once volume joins the QI; 16,850 heavy rows | `risk_eval.json` | The weakest result — residual risk |
| **A5** Differencing | n/a | **0%** recovered (also 0% undefended) | `risk_eval.json` | Blocked by data shape, not provably by our defence |
| **A6** Membership inference | 100% without noise | **54.0%** at ε=1 (ceiling 73.1%, 50% = guessing) | `risk_eval.json` | DP is doing real work |

---

## 7. Decisions and trade-offs

**Why the aggregate release is the headline.** The baseline says 4 known cell
visits identify 99.6% of people. Any release keeping per-subscriber rows *and*
fine location keeps that attack alive. A2 makes this concrete: even in the
k-anonymised record release, 4 known points would single out 99.3% of targets
*if* rows could be linked — the only thing stopping it is the absence of a key.
The aggregate release removes the attack structurally rather than making it
harder, and it still answers the product question: provinces rank at Spearman
0.958 and the bottom-decile worst cells overlap at Jaccard 0.99.

**Why k=10.** The sweep shows the choice is nearly free: across all 24
combinations the worst suppression is 1.22%, and our setting costs 0.32%. Going
from k=5 to k=10 roughly doubles suppression but both are far under the 5%
budget, so we took the stronger setting. k=10 also matches the aggregate cell
threshold, so both releases tell the same story.

**Why ε=1.0.** ε=1 is a widely used default, and A6 shows it does real work:
attacker accuracy falls from 100% (no noise) to 54.0%, against a 73.1% ceiling.
The cost is no longer trivial — contribution bounding raised the noise scale to
11, so the median cell's count is off by 7.3% and the p90 by 116%. ε=2 would
halve the noise but lets the attacker to 57.9%; ε=0.5 doubles the error for
another 2 points of protection. ε=1 sits where the curve bends.

**Why record mode is kept only as a comparison.** It's useful for showing what
k-anonymity alone buys and for analyses needing row-level detail with a tokenised
area. But it retains fine-grained location and 1.1M rows, so it's the riskier
artefact. It is published beside the headline, never instead of it.

**Why session mode is optional.** A session ID re-enables exactly the trajectory
attack the design exists to prevent. It's built, tested and available — but you
must ask for it explicitly, and `--mode all` won't produce it.

**Generalise before suppressing.** Escalating area → province rescues 369,536
rows (33.6%) that would otherwise have been deleted. Suppression is the last
resort, not the first tool.

### With more time

1. **Finish the top-coding fix** — M3 applied the non-zero quantile to volumes
   but not to `winsorise_qoe`, so `http_response_time_avg` is still −98% on the
   mean. Same one-line rule, second code path.
2. **Hierarchical fallback for thin cells** — instead of suppressing outright,
   roll a thin cell up a location hierarchy (cell → municipality → province →
   national) until it reaches k. Would cut the 26.1% cell loss and reduce the
   2G/rural penalty.
3. **Enforce the contribution bound**, don't just use it as a scale. Today 11 is
   the p99 and nothing drops the cells of over-contributing subscribers, so ~1%
   of people get a weaker guarantee than advertised.
4. **Add volume to the k-anonymity QI set** — A4 is the weakest result: 2.0% of
   rows fall below k once an attacker knows roughly how much data the target
   used, and 16,850 heavy-user rows sit in those groups.
5. **Validate on real, multi-day data** — everything here is one fabricated hour.

---

## 8. Known limitations

State these before a judge finds them. Each is already recorded in the repo.

1. **One hour of fabricated data.** 2027-04-30, 16:00–16:50. No multi-day
   linkage exists, so longitudinal risk is **untested, not absent**. Real data
   would behave differently.
2. **`tac` is constant** across all 199,195 subscribers. Device-model risk reads
   as zero because the fabricated data has one device, not because we solved it.
3. **Suppression is uneven.** 2G keeps 82.14% of rows against 99.72% for 4G. The
   worst province keeps 49.40%. The people in thin strata — rural areas, old
   handsets — are the ones the data can say least about. This is the known
   weakness of every threshold method, and it has a fairness dimension worth
   naming.
4. **DP scope is narrower than "ε=1.0" suggests.** It covers `n_subscribers` and
   the choice of published cells. It does **not** cover the QoE medians, p10s,
   p90s or volume sums — those carry no noise — nor the record and session
   releases, nor repeated publication. The contribution bound of 11 is a p99 and
   is not enforced, so roughly 1% of subscribers get a weaker guarantee.
5. **Top-coding still degrades five metrics' means**, `http_response_time_avg`
   by 98%. M3 fixed the volume path (rescuing `im_video_GB_sum` from −100% to
   −14.9%) but not the QoE winsorising path. The release answers "what is
   typical", never "how much in total".
10. **Count accuracy is now materially worse.** Honest contribution bounding
    raised the noise scale from 1 to 11, so the median published count is off by
    7.3% and the p90 by 116%. Small cells are noisy. This is the price of the
    ε=1.0 claim being real rather than nominal.
11. **A5 proves less than it appears.** No slice in this extract ever loses
    exactly one cell, so differencing recovers 0% even with no defences at all.
    Secondary suppression costs 80 cells and is untested on this data.
12. **A4 is the weakest result.** Volume is not part of the k-anonymity QI set,
    so an attacker who also knows roughly how much data a target used pushes
    2.0% of rows below k, with 16,850 heavy-user rows among them.
6. **Cell tokens are reproducible** from raw data + this code (seed 42), so
   tokenisation protects an external recipient, not Elisa.
7. **Utility is measured on surviving cells only.** "99.61% accurate" describes
   the 73.9% of cells that were published. Accuracy and coverage must be quoted
   together.
8. **ePrivacy purpose limitation is unresolved.** Whether Elisa may reuse this
   data for a given purpose is a separate legal question we have not answered.
9. **No formal privacy budget accounting.** We publish once; repeated releases
   would need composition tracking.

---

## 9. Likely judge questions

**1. "Is this data anonymous?"**
Not unconditionally, and we won't claim that. It's anonymous *relative to a
defined recipient* — an Elisa product team with no raw access and no auxiliary
identity data. To Elisa, which holds the source, it isn't, and we say so. We
report ε and empirical attack rates instead of a binary claim.

**2. "Why not just use synthetic data?"**
Synthetic data moves the problem rather than solving it: a generative model
trained on real records can memorise them, and you then need the same
re-identification tests on the output. It also breaks the link to real network
conditions Elisa needs for service-quality decisions. Our approach keeps real
measurements and bounds the risk explicitly.

**3. "Utility is 99.6% — did you actually add any noise?"**
Yes, and it's important to be precise. The 99.6% is about *QoE medians*, which
carry **no noise at all** — the Laplace noise goes on the subscriber counts. At
ε=1 those counts carry median error 7.3% and p90 116%. Medians look untouched
because winsorising only clips the outer 1% of each tail and a median is robust
to that. The honest version: **the counts are genuinely noisy; the medians are
accurate because medians are hard to move — and they are not what DP protects.**

**4. "So what did you actually lose?"**
Four things. 26.1% of cells suppressed entirely. The means of five metrics,
`http_response_time_avg` by 98%. Count precision — the median cell's subscriber
count is off by 7.3%. And all individual-level analysis. We measured all four
rather than discovering them later.

**5. "What if an attacker knows someone's location?"**
That's exactly our headline risk: on raw data, 4 known cell-visits identify
99.6% of subscribers. We measured it after anonymisation too (A2). Neither
published release has a subscriber key, so the attack cannot be run at all. But
be honest about *why*: if rows could somehow be linked, 4 points would still
single out 99.3% of targets at area granularity. The defence is structural —
the absence of a key — not statistical. At province granularity, what the
recipient actually sees, it drops to 3.8%.

**6. "Could Elisa itself re-identify this?"**
Yes. Elisa holds the source extract, and the cell token map is reproducible from
raw data plus our code under seed 42. We state this as a limitation. Our claims
are scoped to a recipient without that access. Insider risk is a governance
control, not a mathematical one.

**7. "Why k=10 and ε=1 specifically?"**
Both from the sweep, not from intuition. k: all 24 combinations suppress under
5%, so we took the stronger setting because it was nearly free — 0.32% at k=10.
ε: A6 measures what each buys. No noise, the attacker is 100% accurate; ε=2,
57.9%; ε=1, 54.0%; ε=0.5, 52.1%. Going below 1 buys about 2 points of
protection for double the count error. ε=1 is where the curve bends, and it's a
common default.

**8. "What did the AI actually do?"**
Mistral Large 3, hosted in Finland, proposed a privacy class for each of the 23
fields from *aggregate statistics and column descriptions only* — it never saw a
row. A human reviewed every field; initials and timestamps are in
`outputs/classification.json`. Claude Code wrote the pipeline and also never
opened the raw file. Both are logged: every LLM call is in
`outputs/llm_calls.jsonl` with a prompt hash.

**9. "How would this run on billions of rows?"**
The transforms are all group-bys and quantiles that map directly onto Spark or
SQL, so the logic ports. Three things need work: the trajectory attack uses an
in-memory inverted index and would need sampling or a distributed join; the leak
guard scans every unique value per column and would need to move to sampling
plus schema-level checks; and k/ε would need re-tuning, since thresholds behave
very differently at scale — bigger data usually means *less* suppression.

**10. "Why publish three releases instead of one?"**
To make the privacy/utility trade-off visible rather than asserted. The
aggregate release is the recommendation; the record release shows what
k-anonymity alone achieves; session mode shows what linkage costs. A single
release would hide the reasoning.

**11. "What's your biggest weakness?"**
Two, and I'd name both. First, A4: volume is not in the k-anonymity QI set, so
an attacker who knows roughly how much data a target used pushes 2.0% of rows
below k, with 16,850 heavy-user rows among them. Second, the top-coding damage —
five metrics have lost their means, `http_response_time_avg` by 98%. We found
the second only because our utility check flagged on mean changes rather than
percentiles; a p95-based check would have reported all-clear.

**12. "How do you know nothing leaked?"**
An automated guard, not a promise. Every distinct identifier is held in memory
(597,585 values) and every file written outside the secure directory is scanned
against it before it reaches its destination. It runs before every commit and
exits non-zero on any finding. It has blocked three real writes during
development.

**13. "Isn't k-anonymity outdated?"**
On its own, yes — it's vulnerable to homogeneity and background-knowledge
attacks, which is precisely why it's not our headline. The recommendation is the
DP aggregate. k-anonymity is the comparison baseline and the safety net on the
record release.

**14. "What about l-diversity?"**
We measured it (A3). Across all 27,291 QI groups, **no group is homogeneous on
the revealing value** of tethering, heavy usage or video. Homogeneous groups do
exist — 94% for video — but they are homogeneous on *False*, which only tells an
attacker what the target didn't do. We excluded `application_category` from the
test because it is itself a quasi-identifier, so every group holds one value by
construction and testing it would return a meaningless 100%.

**15. "Could someone reverse the cell tokens?"**
Not from the release alone — the map lives in memory and is never written. But
with the raw extract and our code, yes, because the permutation is seeded at 42
for reproducibility. That's a deliberate trade and it's documented. An external
recipient can't; Elisa can.

**16. "Why is 2G coverage so much worse?"**
Only 3,236 rows are 2G out of 1.1 million. Any threshold rule hits the rarest
groups hardest, so 2G keeps 81.6% of rows against 99.8% for 4G. It's a real
fairness issue: the technology used disproportionately in rural areas and by
older handsets is the one we can say least about. A hierarchical fallback would
reduce it.

**17. "What happens if you publish this data twice?"**
Repeated releases consume privacy budget and open differencing attacks across
versions. We publish one granularity, once, with no marginals — but we don't
track budget composition, and that's a gap if this became a recurring feed.

**18. "Is the median really enough for a product team?"**
For "where is quality worst", yes — and we tested it: province rankings hold at
Spearman 0.958 and the bottom-decile worst cells overlap at Jaccard 0.99. For capacity planning, which
needs totals, no — and that's exactly what top-coding broke.

**19. "How do you know your attacks are real and not just asserted?"**
Because we check mechanically. `tests/test_evaluate.py` parses `evaluate.py` and
fails any attack function that returns a constant instead of computing one. That
test exists because an earlier draft of M3 hardcoded four of the six results.
There is also a test asserting that no measured accuracy can exceed the
differential-privacy bound — it caught a bug where the evaluation used a
contribution bound of 1 while the release used 11, which had made membership
inference look 83% accurate against a 73% ceiling.

**20. "Your count error is 116% at p90. Is the data usable?"**
For counts of small cells, treat them as indicative, not exact — that is the
honest reading. The median cell (88 subscribers) is off by 7.3%. The large error
is concentrated where cells are near the 10-subscriber floor and the noise scale
is 11. The QoE statistics, which is what the service-quality use case actually
needs, are unaffected: rankings hold at Spearman 0.958 and the bottom-decile
worst cells overlap at Jaccard 0.99. If exact counts mattered more than membership privacy, ε=2 halves
the error.

---

## 10. Cheat sheet

**The ten things to remember.**

1. **1,099,340 rows, 199,195 subscribers, one hour** — 2027-04-30, 16:00–16:50.
2. **4 known cell visits identify 99.6%** of subscribers in raw data. This is why
   the whole design exists.
3. **36% of subscribers** own at least one unique row under the strongest QI set.
4. **Headline: median download throughput within 5% of raw for 99.61% of
   published cells, target 90% — PASS.**
5. **k = 10 distinct subscribers** — not rows. One chatty subscriber never
   satisfies k alone.
6. **ε = 1.0, Laplace, scale 11** (contribution bound 11 ÷ ε). Membership
   inference falls from **100% to 54.0%**; median count error 7.3%.
7. **26.1% of aggregate cells suppressed** (901 primary + 80 secondary); the
   record release loses only 0.32% of rows because it generalises first.
8. **Coverage is uneven: 2G keeps 82.1% of rows vs 99.7% for 4G.** Name it before
   a judge does.
9. **Trajectory protection is structural, not statistical.** No subscriber key
   exists — but if rows could be linked, 4 points would still identify 99.3%.
10. **We never claim "fully anonymous."** Risk is relative to a defined
    recipient; Elisa itself can still re-identify.

**The one-sentence pitch.** *We turned an extract where four known locations
identify 99.6% of people into an aggregate release with differential privacy
where a worst-case attacker's membership guess drops from 100% to 54% — and it
still answers "where is service quality worst" to within 5% on 99.6% of
published cells.*

**If you only defend one thing:** the honesty. Every attack number is measured,
and we have a test that fails the build if an attack is faked. We report the
results that went against us — A4's 16,850 exposed heavy-user rows, A5 proving
less than it looks, five metrics with broken means — alongside the ones that
went well. A leak guard blocked four real mistakes during development.
