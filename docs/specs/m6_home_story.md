# M6 Home — Scrollytelling pipeline story (R2D3-inspired)

All CLAUDE.md rules apply. Branch `m6-prototype`. Owner: Aviral.
Inspiration: r2d3.us "A Visual Introduction to Machine Learning" — use the
TECHNIQUE only (sticky graphic + scrolling text steps, animated dot
transitions). Do not copy its visuals, text or code.

## Architecture
- Standalone static page: `app/static/story/index.html`, `story.js`, `story.css`.
  No build step, no framework. D3 v7 + scrollama, **vendored** into
  `app/static/vendor/` (download once; the page must work offline at the venue).
- Served by Streamlit static serving: set `server.enableStaticServing = true` in
  `.streamlit/config.toml`; files under `app/static/` are served at
  `/app/static/...`. (If static serving doesn't work from app/, move the folder
  to wherever Streamlit expects `static/` relative to the entry script and note it.)
- `app/Home.py`: a short hero (title, one-line pitch, 3 headline metric cards
  from data.headline_numbers()), a large "Start the story →" link opening the
  story in a new tab, and links to the three tool pages. The story's last step
  links back to the Trade-off Explorer.
- Data: `python -m app.export_story` builds `app/static/story/story_data.json`
  from outputs/*.json via app/lib/data.py. Numbers only: headline figures,
  per-step stats, criteria verdicts, coverage by radio type. Nothing row-level.
  The leak guard must scan this file. Numbers in the story text are always
  filled from story_data.json, never hard-coded.

## Honesty rule for the graphic
Dots are an ILLUSTRATIVE simulation: ~400 synthetic dots generated in JS with
a fixed seed, with attributes drawn to roughly match the published aggregate
proportions (radio type shares, province shares). Label it on the page:
"Each dot is an illustrative subscriber — no real records are shown."

## Layout
Desktop: sticky SVG graphic on the right (~60% width), scrolling text steps
on the left. Mobile (<800px): graphic sticky on top, text below. Smooth D3
transitions (600–900ms) between steps, reversible when scrolling back up.
Light and dark mode via CSS variables. Calm palette: neutral dots, one accent
for "at risk", one for "protected", grey for "suppressed".

## Steps (text ≤ 60 words each, plain language, one number per step)
1. **Meet the data.** One hour of network logs: {n_subscribers} subscribers.
   Dots scatter across a map-like field of cell towers.
2. **Strip the identifiers.** Phone numbers, SIM and device IDs removed.
   Each dot drops a small ID tag.
3. **Still unique.** Knowing just 4 places and times singles out {a2_raw}%.
   Four dots light up with trails connecting their tower visits.
4. **Blur place and time.** Towers become areas/provinces, exact times become
   {time_bucket}-minute windows. Dots snap into a province × time grid.
5. **Safety in numbers.** Every published group has at least {k} people.
   Dots cluster; groups under k fade to grey (suppressed). Callout:
   "Rare groups pay the price: 2G keeps {cov_2g}% vs 4G {cov_4g}%."
6. **Publish counts, not people.** Groups collapse into bars; bars jitter
   slightly = calibrated noise (ε = {epsilon}). Explain ε in one sentence.
7. **Try to break it.** An attacker icon runs the six attacks; a scoreboard
   shows the three EDPB criteria (No Record Isolation / No Linkage /
   No Inference) with verdicts under the contextual and simplified approaches.
   Highlight: membership inference {a6}% vs 50% coin flip (bound {a6_bound}%).
8. **Still useful.** Two ranked bar lists side by side (raw vs published,
   worst-10 cells): {u3_overlap}/10 match. {u1}% of cells within 5% on speed.
9. **What we can't promise.** Honest residual risks, 4–5 short lines
   (single fabricated hour, rare groups, DP covers counts only, record release
   fails outliers under worst case, re-assess over time).
10. **You decide.** "Every setting is a trade-off between insight and risk."
    Button → Trade-off Explorer. Secondary → AI Analyst.

## Tests
- export_story writes only numeric/label fields (schema check), no identifier
  column names, and passes the leak guard
- story_data.json has every key the page uses (read keys from story.js with a
  simple regex and assert presence)
- Home.py renders with SECURE_DIR unset (AppTest)

CHECK: `python -m app.export_story`, `streamlit run app/Home.py`, open the
story, scroll all 10 steps forward and back without errors (check the browser
console), test at mobile width, leak guard clean. Commit.
