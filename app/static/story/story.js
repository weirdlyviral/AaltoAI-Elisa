(function () {
  "use strict";

  // ---------------------------------------------------------------- config

  var VB_W = 700;
  var VB_H = 700;
  var PLOT = { left: 104, top: 58, right: 20, bottom: 30 };
  var PLOT_W = VB_W - PLOT.left - PLOT.right;
  var PLOT_H = VB_H - PLOT.top - PLOT.bottom;

  var N_TOWERS = 12;
  var TOWER_COLS = 4;
  var TOWER_ROWS = 3;
  var N_ROWS = 6; // province rows (top 5 + Other)
  var MIN_DOTS_PER_NETWORK = 6;

  var DUR = 850;
  var STAGGER = 400;

  var PIPELINE = ["Collect", "Strip", "Blur", "Group", "Publish", "Attack", "Measure", "Decide"];

  // ?pitch=1 — presenter mode: bigger type and only the beats worth stopping on.
  var PITCH = new URLSearchParams(window.location.search).get("pitch") === "1";
  var PITCH_FONT_SCALE = 1.2;
  var PITCH_STOPS = ["collect", "p4", "suppress", "bars-noisy", "scoreboard", "utility-bars", "decide"];
  // Below this, label sizes would swamp a phone-sized graphic.
  var MAX_UNIT_PX = 1.6;

  var NET_ORDER = ["4G", "5G", "2G"];

  // ------------------------------------------------------------- step text
  // Every curly-brace placeholder is filled from story_data.json at load
  // time; no number below is hard-coded. See docs/specs/m6_home_story_v2.md.

  var STEPS = [
    {
      key: "collect",
      chapter: 0,
      headline: "Meet the data",
      body:
        "Every time a phone uses the network, the equipment logs how well the connection " +
        "worked: download speed, latency, how much data moved. One row is one subscriber's " +
        "traffic in one short window at one cell tower. Elisa's engineers need this to find " +
        "where the network is slow — but a raw row also carries the phone number, the SIM and " +
        "the handset. Watch the dots fade in around the towers: each dot is one subscriber, " +
        "and its colour is the network they were on.",
      stat: { value: "{n_subscribers}", label: "subscribers in a single hour" },
      chip: "profile.py · {n_rows} rows · one hour, one date",
      lens: null,
    },
    {
      key: "tags-off",
      chapter: 1,
      headline: "Strip the direct identifiers",
      body:
        "The obvious first move is to delete whatever names a person outright: the phone " +
        "number, the SIM identity and the handset identity. We drop all three, and the " +
        "pipeline refuses to write any file that still contains one — that check runs before " +
        "every save. Watch the small grey ID tags detach from every dot and fall away. " +
        "Nothing else about the row changes: same tower, same moment, same measured speed.",
      stat: { value: "3", label: "direct identifier columns removed" },
      chip: "anonymise.py · drop msisdn, imsi, imei",
      lens: null,
    },
    {
      key: "rings-dashed",
      chapter: 1,
      headline: "Pseudonymous is not anonymous",
      body:
        "It is tempting to stop here, and plenty of projects do. But removing names does not " +
        "make data anonymous — it makes it pseudonymous. The rows still describe real people, " +
        "and the attributes left behind can still point back at one of them. Regulators treat " +
        "that as personal data. Watch a dashed grey ring appear around every dot: that ring " +
        "means identifiers removed, but still identifiable. The rest of this story is about " +
        "turning those rings green.",
      stat: { value: "0", label: "direct identifiers left — and still not anonymous" },
      chip: "EDPB Guidelines 02/2026 · Annex 1",
      lens: "On its own, deleting identifiers satisfies none of the three criteria.",
    },
    {
      key: "target",
      chapter: 1,
      headline: "Now play the attacker",
      body:
        "To test whether stripped data is really anonymous, we attack it ourselves. Suppose " +
        "you know a handful of places and times where one specific person was — a colleague " +
        "whose desk you share, someone whose commute you know. You have no phone number and " +
        "no account: you only know where they were. Watch one dot take a red ring. That is " +
        "our target. Every other dot is still a candidate, and we now add what the attacker " +
        "knows, one observation at a time.",
      stat: { value: "1", label: "target — everyone else still a candidate" },
      chip: "baseline_risk.py · R2 trajectory uniqueness",
      lens: "EDPB lens: No Record Isolation.",
    },
    {
      key: "p1",
      chapter: 1,
      headline: "One known point narrows nothing",
      body:
        "The attacker's first piece of knowledge: the target was at this tower, in this " +
        "quarter-hour. Watch the first point light up, and watch every dot that was somewhere " +
        "else dim away. Plenty of people are left — a busy cell in a busy window holds " +
        "thousands of subscribers, and being one of them says almost nothing about you. On " +
        "our measured data, a single known point uniquely identifies nobody at all.",
      stat: { value: "{r2_1}%", label: "of subscribers uniquely identified" },
      chip: "baseline_risk.py · R2, p = 1",
      lens: null,
    },
    {
      key: "p2",
      chapter: 1,
      headline: "Two points, and it starts",
      body:
        "Add a second observation: a different tower, a different quarter-hour. Watch the " +
        "first leg of the trail draw, and watch the surviving candidates thin out sharply. " +
        "Being in one place is ordinary; being in two particular places within the same hour " +
        "is far rarer. On our data, two known points already pin down more than one person in " +
        "ten — and the attacker has learned nothing about the network, only about a person.",
      stat: { value: "{r2_2}%", label: "of subscribers uniquely identified" },
      chip: "baseline_risk.py · R2, p = 2",
      lens: null,
    },
    {
      key: "p3",
      chapter: 1,
      headline: "Three points, most people",
      body:
        "A third observation. Watch the trail extend again and the bright dots all but " +
        "vanish. Human movement is intensely distinctive: the sequence of towers you pass " +
        "through in an hour behaves like a fingerprint, even though no single tower means " +
        "anything by itself. With three known points, the large majority of subscribers in " +
        "this extract become unique — exactly one row pattern matches them.",
      stat: { value: "{r2_3}%", label: "of subscribers uniquely identified" },
      chip: "baseline_risk.py · R2, p = 3",
      lens: null,
    },
    {
      key: "p4",
      chapter: 1,
      headline: "Four points, almost everyone",
      body:
        "With a fourth observation only the target is left. This is the measurement that " +
        "drives the whole design: four known tower-and-time pairs single out almost every " +
        "subscriber who moved that much during the hour. Deleting the phone number did " +
        "nothing to stop it. To actually anonymise this data we have to attack the thing that " +
        "makes people unique — the sheer precision of where and when.",
      stat: { value: "{r2_4}%", label: "of subscribers uniquely identified" },
      chip: "baseline_risk.py · R2, p = 4",
      lens: "EDPB lens: No Record Isolation and No Linkage both fail at this stage.",
    },
    {
      key: "blur-place",
      chapter: 2,
      headline: "Blur where",
      body:
        "So we make location coarser. Instead of the exact cell tower we publish an area, and " +
        "where an area holds too few people we fall back to the whole province. Think of " +
        "describing someone as a man in a dark suit rather than the man in the navy pinstripe " +
        "with the beagle: the first description fits thousands of people, the second fits " +
        "one. Watch the towers dissolve into labelled regions and the dots drift into them.",
      stat: { value: "{n_provinces}", label: "provinces as the coarsest fallback" },
      chip: "anonymise.py · area_mode = enb_tokenised",
      lens: "EDPB lens: No Record Isolation.",
    },
    {
      key: "blur-time",
      chapter: 2,
      headline: "Blur when",
      body:
        "Then the same treatment for time. The raw logs resolve to the minute; we round every " +
        "row into a {time_bucket}-minute window, so a whole hour collapses into four columns. " +
        "Watch each region split into those windows. Everybody now sits in a bucket of place " +
        "and time rather than at a point. Look at how thin some rows already are — those " +
        "small groups are exactly where the remaining risk lives.",
      stat: { value: "{time_bucket} min", label: "time resolution, down from one minute" },
      chip: "anonymise.py · time_bucket_minutes = {time_bucket}",
      lens: "EDPB lens: No Record Isolation.",
    },
    {
      key: "counts",
      chapter: 3,
      headline: "Count the people in each bucket",
      body:
        "Blurring alone is not enough — a bucket with one person in it is still that person. So " +
        "before anything is published we count how many distinct subscribers fall into every " +
        "bucket. Watch a count appear on each cell. Note that we count people, not rows: a " +
        "subscriber who generated twenty rows in one bucket counts once. That is the stricter " +
        "reading, and the one that actually matches what an attacker would be trying to isolate.",
      stat: { value: "{k}", label: "distinct people required in any published group" },
      chip: "anonymise.py · k = {k}, counted on distinct subscribers",
      lens: "EDPB lens: No Record Isolation.",
    },
    {
      key: "k-rings",
      chapter: 3,
      headline: "Groups of ten or more are safe",
      body:
        "A bucket holding at least k distinct people gives an attacker no way to isolate one of " +
        "them: on the published attributes, every record in it looks like every other. Watch " +
        "the rings turn from dashed grey to green in every cell that clears the threshold. " +
        "Those green rings are the first real guarantee in this story — not a promise that " +
        "nothing can be learned, but a floor on how precisely anyone can be picked out.",
      stat: { value: "{k}+", label: "distinct subscribers behind every green ring" },
      chip: "anonymise.py · k-anonymity on distinct subscribers",
      lens: "EDPB lens: No Record Isolation.",
    },
    {
      key: "suppress",
      chapter: 3,
      headline: "Rare groups pay the price",
      body:
        "Buckets that stay under the threshold cannot be published at all, so we drop them. " +
        "Watch the thin cells fade out. This is the real cost of anonymisation and it is not " +
        "shared evenly: common combinations survive almost intact while rare ones disappear, " +
        "and the people in rare groups are often exactly the ones a network team most wants to " +
        "see. Older network types take the worst of it.",
      stat: { value: "{cov_2g}% vs {cov_4g}%", label: "of rows kept — 2G against 4G" },
      chip: "anonymise.py · suppress groups below k",
      lens: "EDPB lens: No Record Isolation.",
    },
    {
      key: "bars",
      chapter: 4,
      headline: "Publish counts, not people",
      body:
        "What a product team actually receives is not a pile of rows at all. Each surviving " +
        "bucket collapses into one line: how many people were in it, and the spread of their " +
        "measurements. Watch the dots in every cell fuse into a single bar whose height is the " +
        "count. Individual records stop existing at this point — there is nothing left to " +
        "single out, because the smallest published thing is now a group.",
      stat: { value: "{n_published_cells}", label: "published cells in the real release" },
      chip: "anonymise.py · aggregate release",
      lens: null,
    },
    {
      key: "bars-noisy",
      chapter: 4,
      headline: "Then blur the counts too",
      body:
        "Even a count leaks. If you know everything about a release except whether one person " +
        "is in it, an exact count answers that question. So we add calibrated random noise to " +
        "every published count — differential privacy at a budget of ε = {epsilon}. Watch each " +
        "bar jump to its published value. The noise is small next to a group and large next to " +
        "one person, which is exactly the trade it is meant to make.",
      stat: { value: "ε = {epsilon}", label: "privacy budget on every published count" },
      chip: "anonymise.py · Laplace, scale {dp_scale}, seed 42",
      lens: "EDPB lens: No Inference. Noise protects the counts; the medians are protected by the group-size threshold instead.",
    },
    {
      key: "attacks-isolation",
      chapter: 5,
      headline: "Now try to break it",
      body:
        "A design is only as good as the attacks it survives, so we wrote six and ran them " +
        "against the releases. The first two go after isolation: can anyone point at one record " +
        "and say that is you? Watch the first two cards resolve. A1 checks whether any " +
        "published row stands alone. A4 asks what happens when the attacker also knows roughly " +
        "how much data the target used — the case that still leaves residual risk.",
      stat: { value: "6", label: "attacks implemented and measured, not assumed" },
      chip: "evaluate.py · A1, A4",
      lens: "EDPB lens: No Record Isolation.",
    },
    {
      key: "attacks-linkage",
      chapter: 5,
      headline: "Can anyone join the dots?",
      body:
        "The third attack asks whether two records can be tied back to the same person. In the " +
        "published release they cannot: there is no subscriber key of any kind, not even a " +
        "hash, so there is nothing to join on. That defence is structural rather than " +
        "statistical, and it is worth stating plainly — if we ever added a persistent " +
        "pseudonym, the trajectory attack from earlier in this story would come straight back.",
      stat: { value: "0", label: "keys, hashes or pseudonyms in the release" },
      chip: "evaluate.py · A2",
      lens: "EDPB lens: No Linkage.",
    },
    {
      key: "attacks-inference",
      chapter: 5,
      headline: "What can still be inferred?",
      body:
        "The last three go after inference — not who someone is, but what can be learned about " +
        "them. A3 hunts for groups where everyone shares a revealing attribute. A5 tries to " +
        "reconstruct a suppressed cell by subtracting the cells around it. A6 is the strongest " +
        "adversary we can write: someone holding everyone else's data who only wants to know " +
        "whether you are in the release at all. Watch the last three cards resolve.",
      stat: { value: "{a6}%", label: "membership-inference accuracy against a 50% coin flip" },
      chip: "evaluate.py · A3, A5, A6",
      lens: "EDPB lens: No Inference.",
    },
    {
      key: "scoreboard",
      chapter: 5,
      headline: "The scoreboard, both ways",
      body:
        "The EDPB asks three questions, and the honest answer depends on which attacker you " +
        "assume. Under the contextual approach — an Elisa product team with no raw access, no " +
        "keys and no auxiliary identity data — all three criteria hold. Under the simplified " +
        "approach, which grants capabilities the recipient does not have, the row-level " +
        "record release fails on outliers while the aggregate — the release we actually " +
        "ship — holds, with one named weakness. The verdict rules are written down, not " +
        "improvised per slide.",
      stat: { value: "3 / 3", label: "criteria met by the aggregate release, both approaches" },
      chip: "verdicts.py · rules mirrored in risk_assessment.md",
      lens: null,
    },
    {
      key: "utility-bars",
      chapter: 6,
      headline: "Is any of it still useful?",
      body:
        "Privacy you can measure is worthless if the data stops answering questions, so we " +
        "measured that too. For every published cell we compared the median of each quality " +
        "metric against the same cell computed on raw data. Watch a bar appear for each metric: " +
        "the share of cells landing within {u1_tolerance}% of the truth. Download throughput — " +
        "the number an engineer reaches for first — holds in {u1}% of cells.",
      stat: { value: "{u1}%", label: "of cells keep median download speed within {u1_tolerance}%" },
      chip: "utility.py · U1, tolerance {u1_tolerance}%",
      lens: null,
    },
    {
      key: "utility-target",
      chapter: 6,
      headline: "Where it holds and where it bends",
      body:
        "The line marks the {u1_target}% target we set before running any of this. Every metric " +
        "clears it, but not by the same margin: HTTP response time sits lowest, because " +
        "clipping its long tail moves the middle of that distribution more than it moves " +
        "throughput. Ranking survives as well — provinces ordered by speed come out at a " +
        "Spearman correlation of {u3_spearman}, and the worst tenth of cells is almost the " +
        "same set before and after: {u3_shared} of {u3_union} cells shared.",
      stat: {
        value: "{u3_jaccard}",
        label: "Jaccard overlap of the worst-decile cells ({u3_shared} of {u3_union} shared)",
      },
      chip: "utility.py · U3, bottom decile with ties included",
      lens: null,
    },
    {
      key: "limits",
      chapter: 6,
      headline: "What we cannot promise",
      body:
        "Everything above is measured, which also means everything above is bounded by what we " +
        "measured. Five things we would say to a regulator without being asked:",
      limitations: [
        "This is one fabricated hour on one date. Longitudinal and device-based risks are untested here, not absent.",
        "Rare groups are suppressed rather than protected — the people hardest to see are the ones we drop.",
        "Differential privacy covers the published counts. The medians rely on the group-size threshold instead.",
        "Under the simplified attacker model the record release still fails on outliers; the aggregate is what we recommend.",
        "A risk assessment is true for a moment. Auxiliary data keeps growing, so this needs re-running, not filing.",
      ],
      stat: null,
      chip: "risk_assessment.md · limitations",
      lens: null,
    },
    {
      key: "decide",
      chapter: 7,
      headline: "You decide",
      body:
        "Every setting in this pipeline is a dial between insight and risk. A larger k protects " +
        "more people and deletes more rare groups. A smaller ε adds more noise and blurs more " +
        "counts. No setting is simply correct, which is why the choice belongs to someone who " +
        "can be accountable for it rather than to a default in a config file. The explorer lets " +
        "you move those dials and watch both sides move together.",
      stat: null,
      chip: null,
      lens: null,
      actions: [
        { label: "Open the Trade-off Explorer", path: "Trade-off_Explorer", primary: true },
        { label: "Ask the AI Analyst", path: "AI_Analyst", primary: false },
      ],
    },
  ];

  // ------------------------------------------------------------- utilities

  function mulberry32(seed) {
    var s = seed >>> 0;
    return function () {
      s = (s + 0x6d2b79f5) | 0;
      var t = Math.imul(s ^ (s >>> 15), 1 | s);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function weightedPick(rng, entries) {
    var total = 0;
    for (var i = 0; i < entries.length; i++) total += entries[i][1];
    var x = rng() * total;
    for (var j = 0; j < entries.length; j++) {
      x -= entries[j][1];
      if (x <= 0) return entries[j][0];
    }
    return entries[entries.length - 1][0];
  }

  function fillTemplate(text, data) {
    return text.replace(/\{(\w+)\}/g, function (match, key) {
      var value = data[key];
      return value === undefined || value === null ? match : String(value);
    });
  }

  /* The SVG scales with its container, so a nominal 10px label can land at
     8px on a 1280-wide laptop driving a projector. Express every label size
     in --u, the viewBox unit that currently renders as one CSS pixel, and
     keep --u in sync with the real on-screen scale. */
  function syncTypeScale() {
    var svg = document.getElementById("story-svg");
    if (!svg) return;
    var rect = svg.getBoundingClientRect();
    var rendered = Math.min(rect.width / VB_W, rect.height / VB_H);
    if (!rendered) return;
    var unit = Math.min(1 / rendered, MAX_UNIT_PX) * (PITCH ? PITCH_FONT_SCALE : 1);
    svg.style.setProperty("--u", unit + "px");
    document.documentElement.style.setProperty(
      "--chrome-scale",
      String(PITCH ? PITCH_FONT_SCALE : 1)
    );
  }

  // Colours come from ../tokens.css; there is deliberately no hex fallback here.
  function cssVar(name) {
    var value = getComputedStyle(document.documentElement).getPropertyValue(name);
    value = value && value.trim();
    if (!value) console.error("missing colour token " + name + " (is ../tokens.css loaded?)");
    return value || "currentColor";
  }

  // ------------------------------------------------------------ scene data

  function buildScene(data) {
    var rng = mulberry32(data.dot_seed || 42);

    var towers = [];
    var towerAreaW = PLOT_W - 40;
    var towerAreaH = PLOT_H - 60;
    for (var i = 0; i < N_TOWERS; i++) {
      var col = i % TOWER_COLS;
      var row = Math.floor(i / TOWER_COLS);
      var cw = towerAreaW / TOWER_COLS;
      var ch = towerAreaH / TOWER_ROWS;
      towers.push({
        index: i,
        label: "T-" + String(i + 1).padStart(2, "0"),
        x: PLOT.left + 20 + cw * (col + 0.5) + (rng() - 0.5) * cw * 0.22,
        y: PLOT.top + 40 + ch * (row + 0.5) + (rng() - 0.5) * ch * 0.22,
      });
    }

    var radioEntries = Object.keys(data.radio_shares || { "4G": 100 }).map(function (key) {
      return [key, data.radio_shares[key]];
    });
    var provinceEntries = Object.keys(data.province_shares || { Unknown: 100 })
      .map(function (key) {
        return [key, data.province_shares[key]];
      })
      .sort(function (a, b) {
        return b[1] - a[1];
      });
    var rowProvinces = provinceEntries.slice(0, N_ROWS - 1).map(function (entry) {
      return entry[0];
    });
    rowProvinces.push("Other");

    var dotCount = data.dot_count || 400;
    var dots = [];
    for (var d = 0; d < dotCount; d++) {
      var towerIndex = Math.floor(rng() * towers.length);
      var province = weightedPick(rng, provinceEntries);
      var rowIndex = rowProvinces.indexOf(province);
      if (rowIndex < 0) rowIndex = N_ROWS - 1;
      dots.push({
        id: d,
        homeTower: towerIndex,
        network: weightedPick(rng, radioEntries),
        rowIndex: rowIndex,
        colIndex: Math.floor(rng() * 4),
        jx: rng() - 0.5,
        jy: rng() - 0.5,
        spread: rng() - 0.5,
        angle: rng() * Math.PI * 2,
        radial: Math.sqrt(rng()),
      });
    }

    // 2G is genuinely ~0.3% of traffic, which is under two dots out of 400.
    // Lift every network to a visible floor so step 5's "rare groups pay the
    // price" callout has something to point at; the legend states the real share.
    NET_ORDER.forEach(function (net) {
      if (!data.radio_shares || data.radio_shares[net] === undefined) return;
      var owned = dots.filter(function (dot) {
        return dot.network === net;
      });
      var deficit = MIN_DOTS_PER_NETWORK - owned.length;
      if (deficit <= 0) return;
      var donors = dots.filter(function (dot) {
        return dot.network === "4G";
      });
      for (var n = 0; n < deficit && n < donors.length; n++) {
        donors[Math.floor(rng() * donors.length)].network = net;
      }
    });

    // One target, four (tower, time) observations, shrinking candidate sets.
    // The four towers are grid neighbours so the trail reads as a short walk
    // rather than four jumps across the city.
    var target = Math.floor(rng() * dots.length);
    var startTower = dots[target].homeTower;
    var targetTowers = [startTower];
    while (targetTowers.length < 4) {
      var from = targetTowers[targetTowers.length - 1];
      var options = neighbourTowers(from).filter(function (index) {
        return targetTowers.indexOf(index) === -1;
      });
      if (!options.length) {
        options = towers
          .map(function (_, index) {
            return index;
          })
          .filter(function (index) {
            return targetTowers.indexOf(index) === -1;
          });
      }
      targetTowers.push(options[Math.floor(rng() * options.length)]);
    }

    var candidates = {};
    candidates[1] = dots
      .filter(function (dot) {
        return dot.homeTower === startTower;
      })
      .map(function (dot) {
        return dot.id;
      });
    if (candidates[1].indexOf(target) === -1) candidates[1].push(target);
    candidates[2] = shrink(candidates[1], Math.max(7, Math.round(candidates[1].length * 0.22)), target, rng);
    candidates[3] = shrink(candidates[2], 3, target, rng);
    candidates[4] = [target];

    // Per-cell counts drive k-anonymity, suppression and the published bars.
    var cellCounts = [];
    for (var r = 0; r < N_ROWS; r++) {
      cellCounts.push([0, 0, 0, 0]);
    }
    dots.forEach(function (dot) {
      cellCounts[dot.rowIndex][dot.colIndex] += 1;
    });

    // Illustrative Laplace noise, scaled so the perturbation a reader sees is
    // proportionally the same as the real release's (dp_scale over the real
    // median cell size, applied to this simulation's median cell size).
    var flatCounts = [];
    cellCounts.forEach(function (row) {
      row.forEach(function (count) {
        if (count > 0) flatCounts.push(count);
      });
    });
    var medianCount = d3.median(flatCounts) || 1;
    var noiseScale =
      data.dp_scale && data.median_cell_subscribers
        ? (data.dp_scale / data.median_cell_subscribers) * medianCount
        : 1;

    var noisyCounts = cellCounts.map(function (row) {
      return row.map(function (count) {
        var u = rng() - 0.5;
        var laplace = -noiseScale * Math.sign(u) * Math.log(1 - 2 * Math.abs(u));
        return Math.max(0, Math.round(count + laplace));
      });
    });

    var maxCellCount = d3.max(flatCounts) || 1;

    // One published cell singled out so the DP step can show a concrete
    // true-versus-published pair.
    var noisyExample = null;
    for (var er = 0; er < N_ROWS && !noisyExample; er++) {
      for (var ec = 0; ec < 4; ec++) {
        if (cellCounts[er][ec] >= 10 && noisyCounts[er][ec] !== cellCounts[er][ec]) {
          noisyExample = {
            row: er,
            col: ec,
            count: cellCounts[er][ec],
            noisy: noisyCounts[er][ec],
          };
          break;
        }
      }
    }

    var rareDot =
      dots.filter(function (dot) {
        return dot.network === "2G" && cellCounts[dot.rowIndex][dot.colIndex] < 10;
      })[0] ||
      dots.filter(function (dot) {
        return dot.network === "2G";
      })[0] ||
      null;

    return {
      towers: towers,
      dots: dots,
      rowProvinces: rowProvinces,
      target: target,
      targetTowers: targetTowers,
      candidates: candidates,
      cellCounts: cellCounts,
      noisyCounts: noisyCounts,
      noiseScale: noiseScale,
      maxCellCount: maxCellCount,
      noisyExample: noisyExample,
      rareDot: rareDot,
    };
  }

  function neighbourTowers(index) {
    var col = index % TOWER_COLS;
    var row = Math.floor(index / TOWER_COLS);
    var out = [];
    [
      [1, 0],
      [-1, 0],
      [0, 1],
      [0, -1],
      [1, 1],
      [-1, -1],
    ].forEach(function (delta) {
      var c = col + delta[0];
      var r = row + delta[1];
      if (c < 0 || c >= TOWER_COLS || r < 0 || r >= TOWER_ROWS) return;
      out.push(r * TOWER_COLS + c);
    });
    return out;
  }

  function shrink(pool, size, keep, rng) {
    var rest = pool.filter(function (id) {
      return id !== keep;
    });
    for (var i = rest.length - 1; i > 0; i--) {
      var j = Math.floor(rng() * (i + 1));
      var tmp = rest[i];
      rest[i] = rest[j];
      rest[j] = tmp;
    }
    return [keep].concat(rest.slice(0, Math.max(0, size - 1)));
  }

  // --------------------------------------------------------------- layouts

  function towerPosition(scene, dot) {
    var tower = scene.towers[dot.homeTower];
    var radius = 34 * dot.radial;
    return {
      x: tower.x + Math.cos(dot.angle) * radius,
      y: tower.y + Math.sin(dot.angle) * radius * 0.85,
    };
  }

  function rowCenterY(rowIndex) {
    var rowH = PLOT_H / N_ROWS;
    return PLOT.top + rowH * (rowIndex + 0.5);
  }

  function provincePosition(dot) {
    var rowH = PLOT_H / N_ROWS;
    return {
      x: PLOT.left + PLOT_W * (0.5 + dot.spread * 0.86),
      y: rowCenterY(dot.rowIndex) + dot.jy * rowH * 0.52,
    };
  }

  function gridPosition(dot) {
    var colW = PLOT_W / 4;
    var rowH = PLOT_H / N_ROWS;
    return {
      x: PLOT.left + colW * (dot.colIndex + 0.5) + dot.jx * colW * 0.66,
      y: rowCenterY(dot.rowIndex) + dot.jy * rowH * 0.52,
    };
  }

  // ---------------------------------------------------------- state machine

  function stateFor(key, scene, data, colors) {
    var state = {
      layout: "tower",
      towers: true,
      towerLabels: true,
      tags: false,
      hulls: false,
      rowLabels: false,
      colLabels: false,
      gridLines: false,
      axisTitles: false,
      trailPoints: 0,
      counter: null,
      annotations: [],
      legendRings: [],
      dots: [],
      countBadges: false,
      greenRings: false,
      suppressSmall: false,
      bars: null, // null | "true" | "noisy"
      attacksLit: null, // null | array of attack ids
      scoreboard: false,
      utilityBars: false,
      utilityTarget: false,
      realRelease: false,
    };

    var candidateSet = null;
    var ringByDot = null;

    switch (key) {
      case "collect":
        state.tags = true;
        break;
      case "tags-off":
        break;
      case "rings-dashed":
        ringByDot = "dashed";
        state.legendRings = ["dashed"];
        break;
      case "target":
        ringByDot = "dashed";
        state.legendRings = ["dashed", "risk"];
        state.trailPoints = 0;
        break;
      case "p1":
      case "p2":
      case "p3":
      case "p4":
        ringByDot = "dashed";
        state.legendRings = ["dashed", "risk"];
        state.trailPoints = Number(key.slice(1));
        candidateSet = scene.candidates[state.trailPoints];
        break;
      case "blur-place":
        state.layout = "province";
        state.towers = false;
        state.hulls = true;
        state.rowLabels = true;
        ringByDot = "dashed";
        state.legendRings = ["dashed", "risk"];
        break;
      case "blur-time":
        state.layout = "grid";
        state.towers = false;
        state.hulls = true;
        state.rowLabels = true;
        state.colLabels = true;
        state.gridLines = true;
        state.axisTitles = true;
        ringByDot = "dashed";
        state.legendRings = ["dashed", "risk"];
        break;
      case "counts":
      case "k-rings":
      case "suppress":
        state.realRelease = true;
        state.layout = "grid";
        state.towers = false;
        state.rowLabels = true;
        state.colLabels = true;
        state.gridLines = true;
        state.axisTitles = true;
        state.countBadges = true;
        ringByDot = "dashed";
        state.legendRings = ["dashed", "risk"];
        if (key !== "counts") {
          state.greenRings = true;
          state.legendRings = ["dashed", "safe"];
        }
        if (key === "suppress") {
          state.suppressSmall = true;
          state.legendRings = ["dashed", "safe", "suppressed"];
        }
        break;
      case "bars":
      case "bars-noisy":
        state.realRelease = true;
        state.layout = "grid";
        state.towers = false;
        state.rowLabels = true;
        state.colLabels = true;
        state.gridLines = true;
        state.axisTitles = true;
        state.bars = key === "bars" ? "true" : "noisy";
        state.legendRings = [];
        break;
      case "attacks-isolation":
        state.towers = false;
        state.attacksLit = ["A1", "A4"];
        break;
      case "attacks-linkage":
        state.towers = false;
        state.attacksLit = ["A1", "A4", "A2"];
        break;
      case "attacks-inference":
        state.towers = false;
        state.attacksLit = ["A1", "A4", "A2", "A3", "A5", "A6"];
        break;
      case "scoreboard":
        state.towers = false;
        state.scoreboard = true;
        break;
      case "utility-bars":
        state.towers = false;
        state.utilityBars = true;
        break;
      case "utility-target":
        state.towers = false;
        state.utilityBars = true;
        state.utilityTarget = true;
        break;
      case "limits":
      case "decide":
        state.layout = "grid";
        state.towers = false;
        state.rowLabels = true;
        state.colLabels = true;
        state.gridLines = true;
        state.bars = "noisy";
        state.quiet = true;
        break;
    }

    var candidateLookup = null;
    if (candidateSet) {
      candidateLookup = {};
      candidateSet.forEach(function (id) {
        candidateLookup[id] = true;
      });
    }

    var showTargetRing = ["target", "p1", "p2", "p3", "p4", "blur-place", "blur-time"].indexOf(key) >= 0;

    scene.dots.forEach(function (dot) {
      var pos =
        state.layout === "tower"
          ? towerPosition(scene, dot)
          : state.layout === "province"
          ? provincePosition(dot)
          : gridPosition(dot);

      var ring = ringByDot;
      var opacity = 0.9;
      var radius = 4.2;

      if (candidateLookup && !candidateLookup[dot.id]) {
        ring = "none";
        opacity = 0.09;
      }
      if (showTargetRing && dot.id === scene.target) {
        ring = "risk";
        radius = 8;
        opacity = 1;
      }

      var cellCount = scene.cellCounts[dot.rowIndex][dot.colIndex];
      if (state.greenRings && cellCount >= data.k) {
        ring = "safe";
      }
      if (state.suppressSmall && cellCount < data.k) {
        ring = "none";
        opacity = 0.25;
      }
      if (state.bars || state.attacksLit || state.scoreboard || state.utilityBars) {
        opacity = 0;
        ring = "none";
      }

      state.dots.push({
        id: dot.id,
        x: pos.x,
        y: pos.y,
        r: radius,
        fill: colors.net[dot.network] || colors.net["4G"],
        ring: ring || "none",
        opacity: opacity,
        network: dot.network,
      });
    });

    // ---- annotations and counters, per step

    var targetDot = state.dots[scene.target];

    if (key === "collect") {
      var t0 = scene.towers[1];
      state.annotations.push({
        x: t0.x,
        y: t0.y - 14,
        tx: t0.x + 6,
        ty: t0.y - 52,
        text: "one cell tower · one quarter-hour",
      });
    }

    if (key === "tags-off") {
      state.annotations.push({
        x: scene.towers[4].x,
        y: scene.towers[4].y - 18,
        tx: scene.towers[4].x - 30,
        ty: scene.towers[4].y - 58,
        text: "every row carried a number, a SIM and a handset",
      });
    }

    if (key === "rings-dashed") {
      var anchor = state.dots[scene.candidates[1][1] || 0];
      state.annotations.push({
        x: anchor.x,
        y: anchor.y,
        tx: anchor.x + 44,
        ty: anchor.y - 46,
        text: "dashed = identifiers gone, still identifiable",
      });
    }

    if (key === "target") {
      state.annotations.push({
        x: targetDot.x,
        y: targetDot.y,
        tx: targetDot.x + 46,
        ty: targetDot.y - 44,
        text: "our target",
      });
    }

    if (state.trailPoints > 0) {
      var remaining = scene.candidates[state.trailPoints].length;
      state.counter = {
        value: data["r2_" + state.trailPoints] + "%",
        label: "of subscribers uniquely identified",
      };
      state.annotations.push({
        x: targetDot.x,
        y: targetDot.y,
        tx: targetDot.x + 46,
        ty: targetDot.y - 44,
        text:
          (remaining === 1
            ? "1 candidate left — the target"
            : remaining + " candidates still match") + " (illustrative)",
      });
    }

    if (key === "blur-place") {
      state.annotations.push({
        x: PLOT.left + PLOT_W * 0.5,
        y: rowCenterY(0) - 34,
        tx: PLOT.left + PLOT_W * 0.28,
        ty: PLOT.top - 22,
        text: "exact tower → area, and province where an area is too small",
      });
    }

    if (key === "blur-time") {
      var counts = [];
      for (var r = 0; r < N_ROWS; r++) counts.push(0);
      scene.dots.forEach(function (dot) {
        counts[dot.rowIndex] += 1;
      });
      var sparsest = counts.indexOf(Math.min.apply(null, counts));
      state.annotations.push({
        x: PLOT.left + PLOT_W * 0.78,
        y: rowCenterY(sparsest),
        tx: PLOT.left + PLOT_W * 0.30,
        ty: rowCenterY(sparsest) + 42,
        text: "Some groups are already tiny — the next step deals with that.",
      });
    }

    if (key === "bars" || key === "bars-noisy") {
      var emptyRow = scene.rowProvinces.findIndex(function (_, rowIndex) {
        return scene.cellCounts[rowIndex].every(function (count) {
          return count < data.k;
        });
      });
      if (emptyRow >= 0) {
        state.annotations.push({
          x: PLOT.left + PLOT_W * 0.5,
          y: rowCenterY(emptyRow),
          tx: PLOT.left + PLOT_W * 0.5,
          ty: rowCenterY(emptyRow) + 30,
          text: "no bar here — every bucket in this row was suppressed",
        });
      }
    }

    if (key === "bars-noisy" && scene.noisyExample) {
      var example = scene.noisyExample;
      var geom = cellGeometry(example.row, example.col);
      var maxCount = scene.maxCellCount || 1;
      var topY = geom.baseline - (example.noisy / maxCount) * geom.maxHeight;
      // Park the callout in the empty gutter left of the grid rather than
      // over the bars or under the column headers.
      state.annotations.push({
        x: geom.cx,
        y: topY,
        tx: PLOT.left * 0.34,
        ty: Math.max(PLOT.top + 40, topY),
        text: "true " + example.count + " → published " + example.noisy,
        anchor: "start",
      });
    }

    return state;
  }

  // --------------------------------------------------------------- drawing

  function initGraphic(scene, colors) {
    var svg = d3
      .select("#story-svg")
      .attr("viewBox", "0 0 " + VB_W + " " + VB_H)
      .attr("preserveAspectRatio", "xMidYMid meet");

    var layers = {};
    [
      "grid",
      "hull",
      "tower",
      "bar",
      "badge",
      "trail",
      "dot",
      "tag",
      "panel",
      "annotation",
      "axis",
      "counter",
    ].forEach(function (name) {
      layers[name] = svg.append("g").attr("class", "layer-" + name);
    });

    layers.tower
      .selectAll("g.tower")
      .data(scene.towers)
      .join("g")
      .attr("class", "tower")
      .each(function (tower) {
        var g = d3.select(this);
        g.append("path")
          .attr("class", "tower-mark")
          .attr("d", "M0,-9 L7.5,5 L-7.5,5 Z")
          .attr("transform", "translate(" + tower.x + "," + tower.y + ")");
        g.append("text")
          .attr("class", "tower-label")
          .attr("x", tower.x)
          .attr("y", tower.y + 48)
          .attr("text-anchor", "middle")
          .text(tower.label);
      });

    var dotSel = layers.dot
      .selectAll("circle")
      .data(scene.dots)
      .join("circle")
      .attr("class", "dot")
      .attr("cx", function (d) {
        return towerPosition(scene, d).x;
      })
      .attr("cy", function (d) {
        return towerPosition(scene, d).y;
      })
      .attr("r", 4.2)
      .attr("fill", function (d) {
        return colors.net[d.network] || colors.net["4G"];
      })
      .attr("opacity", 0);

    var tagSel = layers.tag
      .selectAll("rect")
      .data(scene.dots)
      .join("rect")
      .attr("class", "id-tag")
      .attr("width", 9)
      .attr("height", 3.4)
      .attr("rx", 1.2)
      .attr("x", function (d) {
        return towerPosition(scene, d).x + 4;
      })
      .attr("y", function (d) {
        return towerPosition(scene, d).y - 9;
      })
      .attr("opacity", 0);

    return { svg: svg, layers: layers, dotSel: dotSel, tagSel: tagSel };
  }

  function ringStroke(ring, colors) {
    if (ring === "dashed") return colors.ringDashed;
    if (ring === "risk") return colors.ringRisk;
    if (ring === "safe") return colors.ringSafe;
    return "none";
  }

  function ringWidth(ring) {
    if (ring === "none") return 0;
    return ring === "risk" ? 2.2 : 1.4;
  }

  function ringDash(ring) {
    return ring === "dashed" ? "2.5 2" : null;
  }

  function applyState(gfx, scene, state, colors, animate) {
    var duration = animate ? DUR : 0;
    var stagger = animate ? STAGGER : 0;

    function delayFor(d, i) {
      var x = state.dots[i] ? state.dots[i].x : 0;
      return (x / VB_W) * stagger;
    }

    gfx.dotSel
      .transition("dots")
      .duration(duration)
      .delay(delayFor)
      .ease(d3.easeCubicInOut)
      .attr("cx", function (d, i) {
        return state.dots[i].x;
      })
      .attr("cy", function (d, i) {
        return state.dots[i].y;
      })
      .attr("r", function (d, i) {
        return state.dots[i].r;
      })
      .attr("fill", function (d, i) {
        return state.dots[i].fill;
      })
      .attr("opacity", function (d, i) {
        return state.dots[i].opacity;
      })
      .attr("stroke", function (d, i) {
        return ringStroke(state.dots[i].ring, colors);
      })
      .attr("stroke-width", function (d, i) {
        return ringWidth(state.dots[i].ring);
      })
      .attr("stroke-dasharray", function (d, i) {
        return ringDash(state.dots[i].ring);
      });

    gfx.dotSel.classed("is-target", function (d, i) {
      return state.dots[i].ring === "risk";
    });

    gfx.tagSel
      .transition("tags")
      .duration(duration)
      .delay(delayFor)
      .ease(d3.easeCubicInOut)
      .attr("x", function (d, i) {
        return state.dots[i].x + 4;
      })
      .attr("y", function (d, i) {
        return state.tags ? state.dots[i].y - 9 : state.dots[i].y + 26;
      })
      .attr("opacity", state.tags ? 0.75 : 0);

    gfx.layers.tower
      .transition("towers")
      .duration(duration)
      .attr("opacity", state.towers ? 1 : 0);

    drawTrail(gfx, scene, state, duration);
    drawHulls(gfx, scene, state, duration);
    drawAxes(gfx, scene, state, duration);
    drawCountBadges(gfx, scene, state, duration);
    drawBars(gfx, scene, state, duration);
    drawAttackPanel(gfx, state, gfx.data, duration);
    drawScoreboard(gfx, state, gfx.data, duration);
    drawUtilityBars(gfx, state, gfx.data, duration);
    drawAnnotations(gfx, state, duration);
    drawCounter(gfx, state, duration);
  }

  function curvedLeg(from, to) {
    var mx = (from.x + to.x) / 2;
    var my = (from.y + to.y) / 2;
    var dx = to.x - from.x;
    var dy = to.y - from.y;
    var len = Math.sqrt(dx * dx + dy * dy) || 1;
    var bow = Math.min(46, len * 0.24);
    return (
      "M" + from.x + "," + from.y +
      " Q" + (mx - (dy / len) * bow) + "," + (my + (dx / len) * bow) +
      " " + to.x + "," + to.y
    );
  }

  function drawTrail(gfx, scene, state, duration) {
    var points = scene.targetTowers.slice(0, state.trailPoints).map(function (index, order) {
      var tower = scene.towers[index];
      return { x: tower.x, y: tower.y, order: order + 1 };
    });

    var legs = [];
    for (var i = 0; i < points.length - 1; i++) {
      legs.push({ key: i, d: curvedLeg(points[i], points[i + 1]) });
    }

    gfx.layers.trail
      .selectAll("path.trail-leg")
      .data(legs, function (leg) {
        return leg.key;
      })
      .join(
        function (enter) {
          return enter
            .append("path")
            .attr("class", "trail-leg")
            .attr("d", function (leg) {
              return leg.d;
            })
            .attr("opacity", 0)
            .call(function (sel) {
              sel.transition("leg").duration(duration).attr("opacity", 1);
            });
        },
        function (update) {
          return update.attr("d", function (leg) {
            return leg.d;
          });
        },
        function (exit) {
          return exit.transition("leg").duration(duration / 2).attr("opacity", 0).remove();
        }
      );

    gfx.layers.trail
      .selectAll("g.trail-badge")
      .data(points, function (point) {
        return point.order;
      })
      .join(
        function (enter) {
          var g = enter
            .append("g")
            .attr("class", "trail-badge")
            .attr("transform", function (point) {
              return "translate(" + point.x + "," + (point.y - 42) + ")";
            })
            .attr("opacity", 0);
          g.append("circle").attr("r", 7.5);
          g.append("text").text(function (point) {
            return point.order;
          });
          g.transition("badge").duration(duration).attr("opacity", 1);
          return g;
        },
        function (update) {
          return update;
        },
        function (exit) {
          return exit.transition("badge").duration(duration / 2).attr("opacity", 0).remove();
        }
      );
  }

  function drawHulls(gfx, scene, state, duration) {
    if (!state.hulls) {
      gfx.layers.hull.selectAll("path").transition("hull").duration(duration / 2).attr("opacity", 0).remove();
      return;
    }

    var byRow = {};
    scene.dots.forEach(function (dot, i) {
      if (!byRow[dot.rowIndex]) byRow[dot.rowIndex] = [];
      byRow[dot.rowIndex].push([state.dots[i].x, state.dots[i].y]);
    });

    var shapes = Object.keys(byRow)
      .map(function (rowIndex) {
        var hull = d3.polygonHull(byRow[rowIndex]);
        if (!hull) return null;
        var line = d3.line().curve(d3.curveCatmullRomClosed.alpha(0.6));
        return { key: rowIndex, d: line(padHull(hull, 13)) };
      })
      .filter(Boolean);

    gfx.layers.hull
      .selectAll("path")
      .data(shapes, function (shape) {
        return shape.key;
      })
      .join(
        function (enter) {
          return enter
            .append("path")
            .attr("class", "hull-shape")
            .attr("d", function (shape) {
              return shape.d;
            })
            .attr("opacity", 0)
            .call(function (sel) {
              sel.transition("hull").delay(duration * 0.5).duration(duration * 0.6).attr("opacity", 1);
            });
        },
        function (update) {
          return update
            .transition("hull")
            .delay(duration * 0.5)
            .duration(duration * 0.6)
            .attr("d", function (shape) {
              return shape.d;
            })
            .attr("opacity", 1);
        },
        function (exit) {
          return exit.transition("hull").duration(duration / 2).attr("opacity", 0).remove();
        }
      );
  }

  function padHull(hull, pad) {
    var cx = d3.mean(hull, function (p) {
      return p[0];
    });
    var cy = d3.mean(hull, function (p) {
      return p[1];
    });
    return hull.map(function (p) {
      var dx = p[0] - cx;
      var dy = p[1] - cy;
      var len = Math.sqrt(dx * dx + dy * dy) || 1;
      return [p[0] + (dx / len) * pad, p[1] + (dy / len) * pad];
    });
  }

  function drawAxes(gfx, scene, state, duration) {
    var rowData = state.rowLabels
      ? scene.rowProvinces.map(function (name, index) {
          return { key: "row-" + index, text: name, x: PLOT.left - 12, y: rowCenterY(index) };
        })
      : [];

    var colData = state.colLabels
      ? (gfx.timeWindows || []).map(function (label, index) {
          return {
            key: "col-" + index,
            text: label,
            x: PLOT.left + (PLOT_W / 4) * (index + 0.5),
            y: PLOT.top - 14,
          };
        })
      : [];

    var titleData = state.axisTitles
      ? [
          { key: "t-time", text: "Time window →", x: PLOT.left, y: PLOT.top - 34, anchor: "start" },
          { key: "t-area", text: "Area ↓", x: PLOT.left - 12, y: PLOT.top - 34, anchor: "end" },
        ]
      : [];

    var gridData = state.gridLines
      ? [1, 2, 3].map(function (index) {
          return { key: "g-" + index, x: PLOT.left + (PLOT_W / 4) * index };
        })
      : [];

    gfx.layers.axis
      .selectAll("text.axis-label")
      .data(rowData.concat(colData), function (item) {
        return item.key;
      })
      .join(
        function (enter) {
          return enter
            .append("text")
            .attr("class", "axis-label")
            .attr("x", function (item) {
              return item.x;
            })
            .attr("y", function (item) {
              return item.y;
            })
            .attr("text-anchor", function (item) {
              return item.key.indexOf("row-") === 0 ? "end" : "middle";
            })
            .attr("dominant-baseline", "middle")
            .text(function (item) {
              return item.text;
            })
            .attr("opacity", 0)
            .call(function (sel) {
              sel.transition("axis").delay(duration * 0.4).duration(duration * 0.6).attr("opacity", 1);
            });
        },
        function (update) {
          return update;
        },
        function (exit) {
          return exit.transition("axis").duration(duration / 2).attr("opacity", 0).remove();
        }
      );

    gfx.layers.axis
      .selectAll("text.axis-title")
      .data(titleData, function (item) {
        return item.key;
      })
      .join(
        function (enter) {
          return enter
            .append("text")
            .attr("class", "axis-title")
            .attr("x", function (item) {
              return item.x;
            })
            .attr("y", function (item) {
              return item.y;
            })
            .attr("text-anchor", function (item) {
              return item.anchor;
            })
            .text(function (item) {
              return item.text;
            })
            .attr("opacity", 0)
            .call(function (sel) {
              sel.transition("axis").delay(duration * 0.4).duration(duration * 0.6).attr("opacity", 1);
            });
        },
        function (update) {
          return update;
        },
        function (exit) {
          return exit.transition("axis").duration(duration / 2).attr("opacity", 0).remove();
        }
      );

    gfx.layers.grid
      .selectAll("line")
      .data(gridData, function (item) {
        return item.key;
      })
      .join(
        function (enter) {
          return enter
            .append("line")
            .attr("class", "grid-line")
            .attr("x1", function (item) {
              return item.x;
            })
            .attr("x2", function (item) {
              return item.x;
            })
            .attr("y1", PLOT.top - 4)
            .attr("y2", PLOT.top + PLOT_H)
            .attr("opacity", 0)
            .call(function (sel) {
              sel.transition("grid").delay(duration * 0.4).duration(duration * 0.6).attr("opacity", 1);
            });
        },
        function (update) {
          return update;
        },
        function (exit) {
          return exit.transition("grid").duration(duration / 2).attr("opacity", 0).remove();
        }
      );
  }

  function cellGeometry(rowIndex, colIndex) {
    var colW = PLOT_W / 4;
    var rowH = PLOT_H / N_ROWS;
    return {
      cx: PLOT.left + colW * (colIndex + 0.5),
      cy: rowCenterY(rowIndex),
      baseline: rowCenterY(rowIndex) + rowH * 0.42,
      maxHeight: rowH * 0.74,
    };
  }

  function drawCountBadges(gfx, scene, state, duration) {
    var badges = [];
    if (state.countBadges) {
      for (var r = 0; r < N_ROWS; r++) {
        for (var c = 0; c < 4; c++) {
          var geom = cellGeometry(r, c);
          badges.push({
            key: r + "-" + c,
            x: geom.cx,
            y: geom.cy - PLOT_H / N_ROWS / 2 + 13,
            count: scene.cellCounts[r][c],
            small: scene.cellCounts[r][c] < (gfx.k || 10),
          });
        }
      }
    }

    gfx.layers.badge
      .selectAll("text.count-badge")
      .data(badges, function (item) {
        return item.key;
      })
      .join(
        function (enter) {
          return enter
            .append("text")
            .attr("class", "count-badge")
            .attr("x", function (item) {
              return item.x;
            })
            .attr("y", function (item) {
              return item.y;
            })
            .attr("text-anchor", "middle")
            .attr("opacity", 0)
            .call(function (sel) {
              sel
                .text(function (item) {
                  return item.count;
                })
                .classed("is-small", function (item) {
                  return item.small;
                })
                .transition("badge")
                .delay(duration * 0.3)
                .duration(duration * 0.6)
                .attr("opacity", 1);
            });
        },
        function (update) {
          return update
            .text(function (item) {
              return item.count;
            })
            .classed("is-small", function (item) {
              return item.small;
            });
        },
        function (exit) {
          return exit.transition("badge").duration(duration / 2).attr("opacity", 0).remove();
        }
      );
  }

  function drawBars(gfx, scene, state, duration) {
    var bars = [];
    if (state.bars) {
      var maxCount = scene.maxCellCount || 1;
      for (var r = 0; r < N_ROWS; r++) {
        for (var c = 0; c < 4; c++) {
          var trueCount = scene.cellCounts[r][c];
          if (trueCount < (gfx.k || 10)) continue; // suppressed cells are not published
          var shown = state.bars === "noisy" ? scene.noisyCounts[r][c] : trueCount;
          var geom = cellGeometry(r, c);
          bars.push({
            key: r + "-" + c,
            x: geom.cx,
            baseline: geom.baseline,
            height: (shown / maxCount) * geom.maxHeight,
            band:
              state.bars === "noisy"
                ? Math.max(3, (scene.noiseScale / maxCount) * geom.maxHeight)
                : 0,
            count: trueCount,
            shown: shown,
            quiet: !!state.quiet,
          });
        }
      }
    }

    var barW = 34;

    gfx.layers.bar
      .selectAll("rect.cell-bar")
      .data(bars, function (item) {
        return item.key;
      })
      .join(
        function (enter) {
          return enter
            .append("rect")
            .attr("class", "cell-bar")
            .attr("x", function (item) {
              return item.x - barW / 2;
            })
            .attr("width", barW)
            .attr("y", function (item) {
              return item.baseline;
            })
            .attr("height", 0)
            .attr("rx", 2)
            .attr("opacity", 0)
            .call(function (sel) {
              sel
                .transition("bar")
                .delay(duration * 0.35)
                .duration(duration * 0.7)
                .ease(d3.easeCubicInOut)
                .attr("y", function (item) {
                  return item.baseline - item.height;
                })
                .attr("height", function (item) {
                  return item.height;
                })
                .attr("opacity", function (item) {
                  return item.quiet ? 0.25 : 0.9;
                });
            });
        },
        function (update) {
          return update
            .transition("bar")
            .duration(duration)
            .ease(d3.easeCubicInOut)
            .attr("y", function (item) {
              return item.baseline - item.height;
            })
            .attr("height", function (item) {
              return item.height;
            })
            .attr("opacity", function (item) {
              return item.quiet ? 0.25 : 0.9;
            });
        },
        function (exit) {
          return exit.transition("bar").duration(duration / 2).attr("opacity", 0).remove();
        }
      );

    var bands = bars.filter(function (item) {
      return item.band > 0 && !item.quiet;
    });

    gfx.layers.bar
      .selectAll("rect.noise-band")
      .data(bands, function (item) {
        return item.key;
      })
      .join(
        function (enter) {
          return enter
            .append("rect")
            .attr("class", "noise-band")
            .attr("x", function (item) {
              return item.x - barW / 2 - 3;
            })
            .attr("width", barW + 6)
            .attr("y", function (item) {
              return item.baseline - item.height - item.band;
            })
            .attr("height", function (item) {
              return item.band * 2;
            })
            .attr("opacity", 0)
            .call(function (sel) {
              sel.transition("band").delay(duration * 0.6).duration(duration * 0.5).attr("opacity", 1);
            });
        },
        function (update) {
          return update
            .transition("band")
            .duration(duration)
            .attr("y", function (item) {
              return item.baseline - item.height - item.band;
            })
            .attr("height", function (item) {
              return item.band * 2;
            });
        },
        function (exit) {
          return exit.transition("band").duration(duration / 2).attr("opacity", 0).remove();
        }
      );

  }

  var VERDICT_CLASS = { pass: "is-pass", residual: "is-residual", fail: "is-fail" };

  /** Trim an SVG text node until it fits, measuring rather than guessing. */
  function fitText(selection, maxWidth) {
    selection.each(function () {
      var node = this;
      var full = node.textContent;
      if (!full || node.getComputedTextLength() <= maxWidth) return;
      var text = full;
      while (text.length > 4 && node.getComputedTextLength() > maxWidth) {
        text = text.slice(0, -6);
        node.textContent = text.replace(/[\s,;.]+$/, "") + "…";
      }
    });
  }

  function drawAttackPanel(gfx, state, data, duration) {
    var attacks = state.attacksLit ? data.attacks || [] : [];
    var rowH = 88;
    var top = 66;
    var left = 54;
    var right = VB_W - 54;

    var groups = gfx.layers.panel
      .selectAll("g.attack-card")
      .data(attacks, function (item) {
        return item.id;
      });

    groups.exit().transition("panel").duration(duration / 2).attr("opacity", 0).remove();

    var entered = groups.enter().append("g").attr("class", "attack-card").attr("opacity", 0);
    entered.append("rect").attr("class", "attack-box");
    entered.append("text").attr("class", "attack-id");
    entered.append("text").attr("class", "attack-name");
    entered.append("text").attr("class", "attack-measured");
    entered.append("rect").attr("class", "attack-verdict-chip");
    entered.append("text").attr("class", "attack-verdict");

    var merged = entered.merge(groups);

    merged.each(function (item, index) {
      var group = d3.select(this);
      var y = top + index * rowH;
      var lit = state.attacksLit.indexOf(item.id) >= 0;

      group.select("rect.attack-box")
        .attr("x", left)
        .attr("y", y)
        .attr("width", right - left)
        .attr("height", rowH - 14)
        .attr("rx", 8)
        .classed("is-lit", lit);

      group.select("text.attack-id")
        .attr("x", left + 16)
        .attr("y", y + 27)
        .text(item.id);

      group.select("text.attack-name")
        .attr("x", left + 52)
        .attr("y", y + 27)
        .text(item.name);

      group.select("text.attack-measured")
        .attr("x", left + 52)
        .attr("y", y + 49)
        .text(item.measured);

      var chipW = 74;
      group.select("rect.attack-verdict-chip")
        .attr("x", right - chipW - 16)
        .attr("y", y + 16)
        .attr("width", chipW)
        .attr("height", 22)
        .attr("rx", 11)
        .attr("class", "attack-verdict-chip " + (VERDICT_CLASS[item.verdict] || ""))
        .attr("opacity", lit ? 1 : 0);

      group.select("text.attack-verdict")
        .attr("x", right - chipW / 2 - 16)
        .attr("y", y + 31)
        .attr("text-anchor", "middle")
        .text(item.verdict)
        .attr("opacity", lit ? 1 : 0);

      group
        .transition("panel")
        .duration(duration)
        .attr("opacity", lit ? 1 : 0.28);
    });
  }

  function drawScoreboard(gfx, state, data, duration) {
    var rows = state.scoreboard ? data.criteria || [] : [];
    var left = 34;
    // Two releases, each scored under both attacker models.
    var columns = [
      { key: "record_contextual", x: 300, group: 0, text: "contextual" },
      { key: "record_simplified", x: 400, group: 0, text: "simplified" },
      { key: "aggregate_contextual", x: 530, group: 1, text: "contextual" },
      { key: "aggregate_simplified", x: 638, group: 1, text: "simplified" },
    ];
    var groups = [
      { key: "g0", x: 350, text: (data.criteria_columns || [{}])[0].label || "Record" },
      {
        key: "g1",
        x: 584,
        text: ((data.criteria_columns || [])[1] || {}).label || "Aggregate",
      },
    ];
    var top = 176;
    var rowH = 104;

    var header = state.scoreboard
      ? columns
          .map(function (column) {
            return { key: "sub-" + column.key, x: column.x, text: column.text, sub: true };
          })
          .concat(
            groups.map(function (group) {
              return { key: group.key, x: group.x, text: group.text, sub: false };
            })
          )
      : [];

    gfx.layers.panel
      .selectAll("text.score-header")
      .data(header, function (item) {
        return item.key;
      })
      .join(
        function (enter) {
          return enter
            .append("text")
            .attr("class", function (item) {
              return "score-header" + (item.sub ? " is-sub" : "");
            })
            .attr("x", function (item) {
              return item.x;
            })
            .attr("y", function (item) {
              return item.sub ? top - 26 : top - 52;
            })
            .attr("text-anchor", "middle")
            .text(function (item) {
              return item.text;
            })
            .attr("opacity", 0)
            .call(function (sel) {
              sel.transition("score").duration(duration).attr("opacity", 1);
            });
        },
        function (update) {
          return update;
        },
        function (exit) {
          return exit.transition("score").duration(duration / 2).attr("opacity", 0).remove();
        }
      );

    var rowSel = gfx.layers.panel.selectAll("g.score-row").data(rows, function (item) {
      return item.criterion;
    });

    rowSel.exit().transition("score").duration(duration / 2).attr("opacity", 0).remove();

    var entered = rowSel.enter().append("g").attr("class", "score-row").attr("opacity", 0);
    entered.append("line").attr("class", "score-rule");
    entered.append("text").attr("class", "score-name");
    entered.append("text").attr("class", "score-why");
    columns.forEach(function (column) {
      entered.append("rect").attr("class", "score-chip chip-" + column.key);
      entered.append("text").attr("class", "score-chip-text text-" + column.key);
    });

    var merged = entered.merge(rowSel);

    merged.each(function (item, index) {
      var group = d3.select(this);
      var y = top + index * rowH;

      group.select("line.score-rule")
        .attr("x1", left)
        .attr("x2", VB_W - 24)
        .attr("y1", y - 24)
        .attr("y2", y - 24);

      group.select("text.score-name").attr("x", left).attr("y", y + 4).text(item.label);

      // One reasoning line per criterion: the worst verdict across the four
      // cells is the one worth explaining.
      var worst = columns
        .map(function (column) {
          return item[column.key] || {};
        })
        .sort(function (a, b) {
          var order = { fail: 0, residual: 1, pass: 2 };
          return (order[a.status] ?? 3) - (order[b.status] ?? 3);
        })[0];
      group
        .select("text.score-why")
        .attr("x", left)
        .attr("y", y + 26)
        .text((worst || {}).why || "")
        .call(fitText, VB_W - left - 30);

      columns.forEach(function (column) {
        var cell = item[column.key] || {};
        var chipW = 88;
        group.select("rect.chip-" + column.key)
          .attr("x", column.x - chipW / 2)
          .attr("y", y - 14)
          .attr("width", chipW)
          .attr("height", 26)
          .attr("rx", 13)
          .attr("class", "score-chip chip-" + column.key + " " + (VERDICT_CLASS[cell.status] || ""));
        group.select("text.text-" + column.key)
          .attr("x", column.x)
          .attr("y", y + 4)
          .attr("text-anchor", "middle")
          .text(cell.status || "");
      });

      group.transition("score").delay(index * 120).duration(duration).attr("opacity", 1);
    });

    // A2's trajectory number is why linkage was removed, not a verdict on a
    // release that keeps no linkable records. It gets its own line.
    var counterfactual =
      state.scoreboard && data.linkage_counterfactual ? [data.linkage_counterfactual] : [];

    var noteSel = gfx.layers.panel
      .selectAll("g.counterfactual")
      .data(counterfactual, function (item) {
        return item.headline;
      });

    noteSel.exit().transition("score").duration(duration / 2).attr("opacity", 0).remove();

    var noteEntered = noteSel.enter().append("g").attr("class", "counterfactual").attr("opacity", 0);
    noteEntered.append("rect").attr("class", "counterfactual-box");
    noteEntered.append("text").attr("class", "counterfactual-title");
    noteEntered.append("text").attr("class", "counterfactual-body");

    var noteY = top + rows.length * rowH - 10;
    var noteMerged = noteEntered.merge(noteSel);
    noteMerged.select("rect.counterfactual-box")
      .attr("x", left)
      .attr("y", noteY)
      .attr("width", VB_W - left - 24)
      .attr("height", 74)
      .attr("rx", 8);
    noteMerged.select("text.counterfactual-title")
      .attr("x", left + 16)
      .attr("y", noteY + 26)
      .text("Why we removed linkage — " + counterfactualHeadline(counterfactual))
      .call(fitText, VB_W - left - 56);
    noteMerged.select("text.counterfactual-body")
      .attr("x", left + 16)
      .attr("y", noteY + 50)
      .text("Not a verdict: neither release keeps a key, so the attack has nothing to join on.")
      .call(fitText, VB_W - left - 56);
    noteMerged.transition("score").delay(rows.length * 120).duration(duration).attr("opacity", 1);
  }

  function counterfactualHeadline(list) {
    return list.length ? list[0].headline : "";
  }

  function drawUtilityBars(gfx, state, data, duration) {
    var metrics = state.utilityBars ? data.u1_by_metric || [] : [];
    var left = 220;
    var right = VB_W - 96;
    var top = 150;
    var rowH = 74;
    // The axis is zoomed — every metric clears 90%, so a 0-100 scale would
    // flatten the differences. The note below says so on the chart itself.
    var scaleFrom = 85;

    function xFor(pct) {
      return left + ((pct - scaleFrom) / (100 - scaleFrom)) * (right - left);
    }

    var groups = gfx.layers.panel.selectAll("g.utility-row").data(metrics, function (item) {
      return item.metric;
    });

    groups.exit().transition("util").duration(duration / 2).attr("opacity", 0).remove();

    var entered = groups.enter().append("g").attr("class", "utility-row").attr("opacity", 0);
    entered.append("text").attr("class", "utility-label");
    entered.append("text").attr("class", "utility-column");
    entered.append("rect").attr("class", "utility-track");
    entered.append("rect").attr("class", "utility-bar");
    entered.append("text").attr("class", "utility-value");

    var merged = entered.merge(groups);

    merged.each(function (item, index) {
      var group = d3.select(this);
      var y = top + index * rowH;

      group
        .select("text.utility-label")
        .attr("x", left - 14)
        .attr("y", y)
        .attr("text-anchor", "end")
        .text(item.label || item.metric);
      group
        .select("text.utility-column")
        .attr("x", left - 14)
        .attr("y", y + 15)
        .attr("text-anchor", "end")
        .text(item.metric);
      group.select("rect.utility-track").attr("x", left).attr("y", y - 11).attr("width", right - left).attr("height", 22).attr("rx", 4);
      group
        .select("rect.utility-bar")
        .attr("x", left)
        .attr("y", y - 11)
        .attr("height", 22)
        .attr("rx", 4)
        .transition("util")
        .delay(index * 90)
        .duration(duration)
        .ease(d3.easeCubicInOut)
        .attr("width", Math.max(2, xFor(item.pct_within) - left));
      group.select("text.utility-value").attr("x", xFor(item.pct_within) + 10).attr("y", y + 5).text(item.pct_within + "%");

      group.transition("util").delay(index * 90).duration(duration).attr("opacity", 1);
    });

    gfx.layers.panel
      .selectAll("text.axis-note")
      .data(metrics.length ? [{ key: "note" }] : [], function (item) {
        return item.key;
      })
      .join(
        function (enter) {
          return enter
            .append("text")
            .attr("class", "axis-note")
            .attr("x", left)
            .attr("y", top + metrics.length * rowH + 4)
            .text("horizontal axis starts at " + scaleFrom + "%, not 0%")
            .attr("opacity", 0)
            .call(function (sel) {
              sel.transition("util").duration(duration).attr("opacity", 1);
            });
        },
        function (update) {
          return update;
        },
        function (exit) {
          return exit.remove();
        }
      );

    var target = state.utilityTarget && data.u1_target ? [{ key: "target", pct: data.u1_target }] : [];

    gfx.layers.panel
      .selectAll("g.utility-target")
      .data(target, function (item) {
        return item.key;
      })
      .join(
        function (enter) {
          var group = enter.append("g").attr("class", "utility-target").attr("opacity", 0);
          group
            .append("line")
            .attr("x1", function (item) {
              return xFor(item.pct);
            })
            .attr("x2", function (item) {
              return xFor(item.pct);
            })
            .attr("y1", top - 34)
            .attr("y2", top + metrics.length * rowH - 30);
          group
            .append("text")
            .attr("x", function (item) {
              return xFor(item.pct);
            })
            .attr("y", top - 42)
            .attr("text-anchor", "middle")
            .text(function (item) {
              return "target " + item.pct + "%";
            });
          group.transition("util").duration(duration).attr("opacity", 1);
          return group;
        },
        function (update) {
          return update;
        },
        function (exit) {
          return exit.transition("util").duration(duration / 2).attr("opacity", 0).remove();
        }
      );
  }

  function drawAnnotations(gfx, state, duration) {
    var groups = gfx.layers.annotation
      .selectAll("g.annotation")
      .data(state.annotations, function (item) {
        return item.text;
      });

    groups.exit().transition("anno").duration(duration / 2).attr("opacity", 0).remove();

    var entered = groups
      .enter()
      .append("g")
      .attr("class", "annotation")
      .attr("opacity", 0);

    entered.append("path").attr("class", "annotation-line");
    entered.append("rect").attr("class", "annotation-plate");
    entered.append("text").attr("class", "annotation-text");

    var merged = entered.merge(groups);

    merged.select("path").attr("d", function (item) {
      return "M" + item.x + "," + item.y + " L" + item.tx + "," + item.ty;
    });

    merged
      .select("text")
      .attr("x", function (item) {
        return item.tx;
      })
      .attr("y", function (item) {
        return item.ty - 8;
      })
      .attr("text-anchor", function (item) {
        return item.anchor || (item.tx < VB_W * 0.45 ? "start" : "middle");
      })
      .text(function (item) {
        return item.text;
      });

    // Size a plate behind each label so callouts stay readable over dots.
    merged.each(function () {
      var group = d3.select(this);
      var textNode = group.select("text").node();
      if (!textNode) return;
      var box = textNode.getBBox();
      group
        .select("rect")
        .attr("x", box.x - 6)
        .attr("y", box.y - 3)
        .attr("width", box.width + 12)
        .attr("height", box.height + 6)
        .attr("rx", 4);
    });

    merged.transition("anno").delay(duration * 0.55).duration(duration * 0.55).attr("opacity", 1);
  }

  function drawCounter(gfx, state, duration) {
    var data = state.counter ? [state.counter] : [];
    var groups = gfx.layers.counter.selectAll("g.counter-box").data(data, function (item) {
      return item.label;
    });

    groups.exit().transition("counter").duration(duration / 3).attr("opacity", 0).remove();

    var entered = groups.enter().append("g").attr("class", "counter-box").attr("opacity", 0);
    entered
      .append("text")
      .attr("class", "counter-value")
      .attr("x", VB_W - 24)
      .attr("y", 86)
      .attr("text-anchor", "end");
    entered
      .append("text")
      .attr("class", "counter-label")
      .attr("x", VB_W - 24)
      .attr("y", 106)
      .attr("text-anchor", "end");

    var merged = entered.merge(groups);
    merged.select("text.counter-value").text(function (item) {
      return item.value;
    });
    merged.select("text.counter-label").text(function (item) {
      return item.label;
    });
    merged.transition("counter").duration(duration / 2).attr("opacity", 1);
  }

  // ------------------------------------------------------------ chrome: DOM

  function renderPipeline(activeChapter, onJump) {
    var container = document.getElementById("pipeline");
    container.innerHTML = "";
    PIPELINE.forEach(function (name, index) {
      if (index > 0) {
        var sep = document.createElement("span");
        sep.className = "pipeline-sep";
        sep.textContent = "›";
        container.appendChild(sep);
      }
      var pill = document.createElement("span");
      pill.className =
        "pipeline-stage" +
        (index === activeChapter ? " is-current" : index < activeChapter ? " is-done" : "");
      pill.textContent = name;
      pill.setAttribute("role", "button");
      pill.setAttribute("tabindex", "0");
      pill.title = "Jump to " + name;
      pill.addEventListener("click", function () {
        onJump(index);
      });
      container.appendChild(pill);
    });
  }

  function renderPanelTag(state) {
    var tag = document.getElementById("panel-tag");
    var measured = !!(state.attacksLit || state.scoreboard || state.utilityBars);
    tag.className = "panel-tag " + (measured ? "is-measured" : "is-illustrative");
    tag.textContent = measured ? "measured" : "illustrative";
  }

  function renderRealRelease(state, data) {
    var box = document.getElementById("real-release");
    if (!state.realRelease) {
      box.hidden = true;
      return;
    }
    box.hidden = false;
    box.innerHTML =
      '<span class="tag is-measured">measured</span> ' +
      "Real release: <strong>" +
      data.real_pct_cells_suppressed +
      "% of cells hidden</strong> (" +
      Number(data.real_cells_in).toLocaleString("en-US") +
      " → " +
      Number(data.n_published_cells).toLocaleString("en-US") +
      "), <strong>" +
      data.real_pct_subscribers_covered +
      "% of subscribers still counted</strong>. The dots above are a smaller " +
      "simulation, so its suppressed share will not match exactly.";
  }

  function swatchFill(color) {
    return (
      '<svg class="legend-swatch" viewBox="0 0 13 13"><circle cx="6.5" cy="6.5" r="4.6" fill="' +
      color +
      '"></circle></svg>'
    );
  }

  function swatchRing(color, dashed) {
    return (
      '<svg class="legend-swatch" viewBox="0 0 13 13"><circle cx="6.5" cy="6.5" r="4.4" fill="none" stroke="' +
      color +
      '" stroke-width="1.6"' +
      (dashed ? ' stroke-dasharray="2.5 2"' : "") +
      "></circle></svg>"
    );
  }

  function swatchFaded(color) {
    return (
      '<svg class="legend-swatch" viewBox="0 0 13 13"><circle cx="6.5" cy="6.5" r="4.6" fill="' +
      color +
      '" opacity="0.25"></circle></svg>'
    );
  }

  var RING_LEGEND = {
    dashed: ["ringDashed", "identifiers removed", true],
    risk: ["ringRisk", "unique / at risk", false],
    safe: ["ringSafe", "protected in a group", false],
    suppressed: [null, "suppressed — not published", false],
  };

  function renderLegend(state, colors, data) {
    var html =
      '<div class="legend-group"><p class="legend-title">Fill · network</p>' +
      NET_ORDER.filter(function (net) {
        return data.radio_shares && data.radio_shares[net] !== undefined;
      })
        .map(function (net) {
          return (
            '<div class="legend-row">' +
            swatchFill(colors.net[net]) +
            "<span>" +
            net +
            " · " +
            data.radio_shares[net] +
            "%</span></div>"
          );
        })
        .join("") +
      "</div>";

    if (state.legendRings.length) {
      html +=
        '<div class="legend-group"><p class="legend-title">Ring · privacy status</p>' +
        state.legendRings
          .map(function (ringKey) {
            var spec = RING_LEGEND[ringKey];
            if (!spec) return "";
            var swatch = spec[0]
              ? swatchRing(colors[spec[0]], spec[2])
              : swatchFaded(colors.net["4G"]);
            return '<div class="legend-row">' + swatch + "<span>" + spec[1] + "</span></div>";
          })
          .join("") +
        "</div>";
    }

    document.getElementById("legend").innerHTML = html;
  }

  /* The story is served from its own port, so links back into the Streamlit
     app use the origin the reader arrived from. */
  function appBaseUrl() {
    try {
      if (document.referrer) return new URL(document.referrer).origin;
    } catch (error) {
      /* fall through to the default below */
    }
    return "http://localhost:8501";
  }

  function buildStepSections(data) {
    var display = Object.assign({}, data, {
      n_subscribers: Number(data.n_subscribers).toLocaleString("en-US"),
      n_rows: Number(data.n_rows).toLocaleString("en-US"),
    });
    var pane = document.getElementById("text-pane");
    var spacer = pane.querySelector(".step-spacer");

    STEPS.forEach(function (step, index) {
      var section = document.createElement("section");
      section.className = "step";
      section.dataset.stepIndex = String(index);

      var html = '<div class="step-inner">';
      html += '<div class="step-chapter">' + PIPELINE[step.chapter] + "</div>";
      html += '<h2 class="step-headline">' + step.headline + "</h2>";
      html += '<p class="step-body">' + fillTemplate(step.body, display) + "</p>";
      if (step.limitations) {
        html +=
          '<ul class="step-limits">' +
          step.limitations
            .map(function (line) {
              return "<li>" + fillTemplate(line, display) + "</li>";
            })
            .join("") +
          "</ul>";
      }
      if (step.actions) {
        html +=
          '<div class="step-actions">' +
          step.actions
            .map(function (action) {
              return (
                '<a class="step-button' +
                (action.primary ? "" : " is-secondary") +
                '" href="' +
                appBaseUrl() +
                "/" +
                action.path +
                '">' +
                action.label +
                "</a>"
              );
            })
            .join("") +
          "</div>";
      }
      if (step.stat) {
        // A stat whose template pulls a placeholder out of story_data.json is
        // a measured figure; one written as a plain literal is just prose.
        var measured = /\{\w+\}/.test(step.stat.value) || /\{\w+\}/.test(step.stat.label);
        html +=
          '<div class="step-stat"><div class="step-stat-value">' +
          fillTemplate(step.stat.value, display) +
          (measured ? '<span class="tag is-measured">measured</span>' : "") +
          '</div><div class="step-stat-label">' +
          fillTemplate(step.stat.label, display) +
          "</div></div>";
      }
      if (step.lens) {
        html += '<div class="step-lens">' + fillTemplate(step.lens, display) + "</div>";
      }
      if (step.chip) {
        html += '<div class="step-chip">' + fillTemplate(step.chip, display) + "</div>";
      }
      html += "</div>";

      section.innerHTML = html;
      pane.insertBefore(section, spacer);
    });
  }

  function attachTooltip(gfx, scene) {
    var tip = document.getElementById("dot-tooltip");
    gfx.dotSel
      .on("mousemove", function (event, dot) {
        var status = d3.select(this).attr("stroke-dasharray")
          ? "identifiers removed"
          : d3.select(this).attr("stroke") === "none" || !Number(d3.select(this).attr("stroke-width"))
          ? "raw record"
          : "flagged";
        tip.innerHTML =
          "<strong>" + dot.network + "</strong> · " + status +
          '<span class="tip-flag">illustrative dot</span>';
        tip.style.left = event.clientX + 14 + "px";
        tip.style.top = event.clientY + 14 + "px";
        tip.classList.add("is-visible");
      })
      .on("mouseleave", function () {
        tip.classList.remove("is-visible");
      });
  }

  // ------------------------------------------------------------------ boot

  function boot(data) {
    var colors = {
      net: {
        "4G": cssVar("--net-4g"),
        "5G": cssVar("--net-5g"),
        "2G": cssVar("--net-2g"),
      },
      ringDashed: cssVar("--ring-dashed"),
      ringRisk: cssVar("--ring-risk"),
      ringSafe: cssVar("--ring-safe"),
    };

    buildStepSections(data);

    var scene = buildScene(data);
    var gfx = initGraphic(scene, colors);
    syncTypeScale();
    gfx.timeWindows = data.time_windows || ["", "", "", ""];
    gfx.data = data;
    gfx.k = data.k || 10;
    attachTooltip(gfx, scene);

    var titleCard = document.getElementById("title-card");
    var activeIndex = 0;

    function render(stepIndex, animate) {
      var step = STEPS[stepIndex];
      if (!step) return;
      var state = stateFor(step.key, scene, data, colors);
      applyState(gfx, scene, state, colors, animate !== false);
      activeIndex = stepIndex;
      renderPipeline(step.chapter, jumpToChapter);
      renderLegend(state, colors, data);
      renderPanelTag(state);
      renderRealRelease(state, data);
    }

    // The title card belongs to the very top of the page, not to step 1:
    // it fades the moment the reader scrolls and returns if they come back.
    function syncTitleCard() {
      titleCard.classList.toggle("is-hidden", window.scrollY > 60);
    }
    window.addEventListener("scroll", syncTitleCard, { passive: true });
    syncTitleCard();

    // On phones the sticky graphic covers the top ~41% of the viewport, so the
    // step has to trigger lower down to land in the readable area.
    function stepOffset() {
      return window.matchMedia("(max-width: 900px)").matches ? 0.8 : 0.6;
    }

    // Presenter mode keeps only the beats worth stopping on, so a scroll or
    // an arrow key moves between slides rather than between sub-steps.
    var visibleSteps = [];
    document.querySelectorAll(".step").forEach(function (section) {
      var index = Number(section.dataset.stepIndex);
      var keep = !PITCH || PITCH_STOPS.indexOf(STEPS[index].key) >= 0;
      section.classList.toggle("is-pitch-hidden", !keep);
      if (keep) visibleSteps.push({ index: index, element: section });
    });

    if (PITCH) {
      var hint = document.createElement("div");
      hint.className = "pitch-hint";
      hint.textContent = "presenter mode · ← → to move";
      document.body.appendChild(hint);
    }

    function scrollToStep(stepIndex) {
      var match = visibleSteps.filter(function (entry) {
        return entry.index >= stepIndex;
      })[0];
      (match || visibleSteps[visibleSteps.length - 1]).element.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    }

    function jumpToChapter(chapter) {
      for (var i = 0; i < STEPS.length; i++) {
        if (STEPS[i].chapter === chapter) return scrollToStep(i);
      }
    }

    function stepFromChapter(delta) {
      var current = STEPS[activeIndex] ? STEPS[activeIndex].chapter : 0;
      var target = Math.max(0, Math.min(PIPELINE.length - 1, current + delta));
      jumpToChapter(target);
    }

    document.addEventListener("keydown", function (event) {
      if (event.key === "ArrowRight" || event.key === "PageDown") {
        event.preventDefault();
        stepFromChapter(1);
      } else if (event.key === "ArrowLeft" || event.key === "PageUp") {
        event.preventDefault();
        stepFromChapter(-1);
      }
    });

    var scroller = window.scrollama();
    scroller
      .setup({ step: ".step:not(.is-pitch-hidden)", offset: stepOffset() })
      .onStepEnter(function (response) {
        var sections = document.querySelectorAll(".step");
        for (var i = 0; i < sections.length; i++) sections[i].classList.remove("is-active");
        response.element.classList.add("is-active");
        render(Number(response.element.dataset.stepIndex), true);
      });

    window.addEventListener("resize", function () {
      syncTypeScale();
      scroller.offset(stepOffset());
      scroller.resize();
    });

    // Initial paint: dots fade in around the towers.
    render(0, false);
    gfx.dotSel
      .transition("intro")
      .duration(900)
      .delay(function (d, i) {
        return (i / scene.dots.length) * 600;
      })
      .attr("opacity", 0.9);

    window.__story = { render: render, stepCount: STEPS.length };
  }

  fetch("story_data.json")
    .then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    })
    .then(boot)
    .catch(function (error) {
      document.body.innerHTML =
        '<p class="story-error">Could not load story_data.json — run ' +
        "<code>python -m app.export_story</code> first, then reload. (" +
        error +
        ")</p>";
    });
})();
