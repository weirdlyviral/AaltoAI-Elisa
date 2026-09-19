# M6 Home story — v2 design brief

Keep the architecture (vendored D3 + scrollama, static server, export_story,
illustrative seeded dots, honesty banner). This brief replaces the VISUAL and
NARRATIVE design of steps 1–4 and specifies 5–10 in the same language.
Technique inspiration only (r2d3.us); no copied visuals, text or code.

## Design rules (apply to every step)
1. **One change per step.** Each step (or sub-step) changes exactly ONE visual
   variable: position OR colour OR ring OR size OR shape. Never two at once.
2. **The text names what moves.** Every step's text says what the reader should
   watch ("Watch the rings turn from red to green").
3. **Staged, staggered motion.** Transitions 700–1000ms, easeCubicInOut, with a
   per-dot stagger (0–400ms by x-position) so the eye can follow the flow. If a
   step needs two changes, run them sequentially as two scroll sub-steps.
4. **Annotate in the graphic.** An annotation layer in the SVG: labels, thin
   leader lines and callouts pointing at what changed ("these 4 are unique").
   Axis labels appear only when axes become meaningful.
5. **Fully reversible.** Every step renders from a state function
   `render(stepIndex, progress)`; scrolling up restores the exact prior state.

## Dual encoding for dots (always visible legend, top-left of graphic)
- **Fill = network type** (what the dot IS): 4G, 5G, 2G/other — three
  distinguishable colours, colour-blind safe, work in light and dark.
- **Ring (stroke) = privacy status** (what we've DONE to it):
  - none (step 1),
  - dashed grey = "identifiers removed" (step 2),
  - red = "unique / at risk",
  - green = "protected in a group of ≥ k",
  - no ring + 25% opacity = "suppressed (hidden)".
The legend updates to show only the states introduced so far.

## Pipeline progress bar
A slim sticky bar above the graphic: Collect → Strip → Blur → Group → Publish
→ Attack → Measure → Decide. The current stage is highlighted; the reader always
knows where they are in the pipeline.

## Text per step
Each step card has: a short headline (≤ 8 words); body text of 70–110 words in
plain language (what happens, why, and what to watch); one big stat pulled from
story_data.json; a small grey "In our pipeline" chip naming the module and
parameter (e.g. `anonymise.py · time_bucket_minutes = 15`); and where relevant
one line "EDPB lens:" naming the criterion it addresses.

## Steps
1. **Meet the data.** Dots appear clustered around synthetic tower markers
   (small triangles). Fill colours reveal network types as they fade in. Text:
   what one row is (a subscriber's traffic in a time window at a tower) and why
   it's valuable. Stat: {n_subscribers} subscribers in one hour.
2. **Strip the identifiers.** Each dot has a small grey tag "ID ••••"; the tags
   detach and fall away with the stagger, then the rings become dashed grey.
   Text: phone number, SIM ID and device ID are removed; why that alone isn't
   anonymisation (pseudonymous ≠ anonymous). EDPB lens: data is still
   identifiable if attributes combine uniquely.
3. **Still unique.** Scroll sub-steps using the REAL baseline curve from
   baseline_risk.json (R2, p = 1..4): pick one highlighted target dot; for
   p = 1, 2, 3, 4 known (tower, time) points, draw the target's trail one leg
   at a time and dim all dots that DON'T match; a counter shows "% of people
   uniquely identified: {r2[p]}%". Rings turn red on the target. Text: the
   "4 points" insight in one sentence, citing that this is our measured number.
   EDPB lens: No Linkage / No Record Isolation.
4. **Blur place and time.** Two sub-steps. (a) Place: towers merge into
   labelled region shapes (convex hulls) and dots drift into their region.
   (b) Time: regions become columns and dots split into rows of
   {time_bucket}-minute windows; axis labels "Area →", "Time window ↓" appear.
   Text: generalisation explained with the "black suit + dog" intuition in our
   own words. Chip: time_bucket_minutes, area mode.
5. **Safety in numbers.** Each grid cell shows a count badge. Cells with ≥ k:
   dots get green rings. Cells with < k: dots fade to suppressed. Then a callout
   on the 2G dots: "Rare groups pay the price: 2G keeps {cov_2g}% vs 4G {cov_4g}%."
   Text: k-anonymity counted on distinct people, not rows; suppression; why rare
   groups lose most. EDPB lens: No Record Isolation (para 55).
6. **Publish counts, not people.** Dots in each cell collapse (morph) into a
   bar whose height is the count; then (sub-step) bars jitter to their noisy
   value with a thin ± band, and one bar is annotated "true 42 → published 45"
   (illustrative). Text: differential privacy in two sentences, ε = {epsilon},
   and what it does NOT cover (medians are protected by thresholds, not noise).
7. **Try to break it.** Six attack cards (A1–A6) in a column; each one lights
   up in turn, with a thin line to the part of the graphic it targets, and ends
   in a verdict chip. Then a scoreboard of the three EDPB criteria × {contextual,
   simplified}. Highlight A6: attacker accuracy {a6}% vs 50% coin flip
   (theoretical ceiling {a6_bound}%).
8. **Still useful.** Slope chart: the worst-10 cells ranked on raw (left) vs
   published (right); near-horizontal lines = preserved. Big stat:
   {u3_overlap}/10 match; secondary: {u1}% of cells within 5% on speed.
9. **What we can't promise.** A text-first step with 5 icon rows (single
   fabricated hour; rare groups suppressed; DP covers counts only; the record
   release fails outlier tests under worst case; re-assess as tech changes).
   The graphic dims to a quiet state.
10. **You decide.** Text: every setting is a trade-off between insight and risk.
    Primary button → Trade-off Explorer; secondary → AI Analyst.

## Visual polish
- Typography: a serif for headlines (Google Fonts), clean sans for body; body
  18px, generous line height; step cards with lots of whitespace.
- Background: soft off-white (light) / deep navy-grey (dark); graphic sits on
  a subtle panel.
- Dots radius 4–5px; hover shows an illustrative tooltip (network type,
  status) labelled "illustrative".
- Step 1 opening: a title card over the graphic ("How do you share network data
  without sharing people?") that fades on first scroll.

## Home.py polish (Streamlit)
Hide default Streamlit chrome (menu, footer) via CSS, use the same fonts and
palette as the story, a large hero line, and the 3 metric cards in a styled row.

## Data needed in story_data.json (add if missing)
r2_by_points {1..4}, cov_2g, cov_4g, k, epsilon, a6, a6_bound, u1, u3_overlap,
criteria verdicts, attack verdicts A1–A6. All read from outputs via data.py.

## Verification
Headless Chromium: screenshot every step and sub-step at 1440px and 390px,
forward and backward; 0 console errors. Put the screenshots in
$SECURE_DIR/tmp/story_shots/ (outside the repo) and summarise what each shows.
Tests as before (schema, keys, leak guard). Commit after my review.
