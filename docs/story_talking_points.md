# Story page — talking points

What to say over each beat of the scrollytelling page (`app/static/story/`).

Split three ways:

| Chapters | Beats | Who |
|---|---|---|
| Rules | 1 | Aviral |
| Collect → Publish | 2–9 | Teammate |
| Attack → Decide, then the two tools | 10–15 | Aviral |

Assume a mixed panel. Some of them know what k-anonymity is, some don't. Rule
of thumb for the whole talk: use the real term once, then say what it means in
one short sentence, then carry on using it. Don't explain it twice and don't
avoid it.

Run with `?pitch=1`. That makes the text bigger and only stops on eight beats:
**rules-criteria, p4, suppress, bars-noisy, scoreboard, utility-target, comply,
decide**. The rest scroll past while you keep talking. Those eight are marked
**[stop]** below.

Every number on the page is read from `story_data.json` at load time, so read
what's on screen rather than what's written here.

About six minutes. Roughly 1:00 / 2:30 / 2:30.

---

## Beats 1 — Aviral

### 1. "What we have to prove" [stop]

The screen opens with the question and three tiles.

Start with the question on screen: how do you share network data without
sharing the people in it.

Then set up the honest framing early, because it makes everything after it
easier to believe:

- Nobody can promise a dataset is anonymous. What you can do is say who's
  getting it, and then test whether that person can pull someone out of it.
- Ours is an Elisa product team. No access to the raw data, no separate list of
  customers to match against. That matters — the same dataset is much less safe
  in the hands of someone who already holds the original, and Elisa does. So
  none of our claims cover Elisa itself.

Then read the three tiles, slowly, because the scoreboard at the end scores
exactly these three and nothing else:

- Can you pick one person out?
- Can you tell that two rows are the same person?
- Can you learn something specific about someone?

These come from the EDPB anonymisation criteria. Worth naming for the people on
the panel who'll recognise it.

**Hand over:** "That's the bar. Here's what we had to clear it with."

---

## Beats 2–9 — Teammate

The shape of this section: the data is more personal than it looks, taking the
names off does almost nothing, so here's what actually works. Beat 5 is where
the room should sit up. Beat 8 is where you admit what it costs.

### 2. "Meet the data"

One row is one person, at one tower, in one short window — how fast their
connection was, how much they downloaded. Every dot on screen is a subscriber.

Just under 200,000 of them, all in a single hour on a single day.

And in the raw file, every one of those rows also has the phone number, the SIM
and the phone's hardware ID sitting on it.

### 3. "Removing names is not enough"

First thing we do is drop all three of those. The pipeline will refuse to write
a file that still has one in it, so that's enforced in code rather than being
something we remembered to do.

The rings go dashed on screen. Identifiers gone, people still findable.

The word for that is pseudonymised, not anonymised, and it's where a lot of
projects stop.

### 4. "Two places, and it starts"

Now be the attacker for a second. Say the only thing you know about someone is
where they were and roughly when.

One tower, one quarter of an hour: that tells you nothing, it's a crowd. Two
already narrows it to one specific person for about one subscriber in eight.

### 5. "Four places, almost everyone" [stop]

Four gets you to 99.6%.

Say the caveat yourself, don't wait to be asked: that's among people who moved
between at least four different towers in the hour. But that's a normal
commute.

The point of this beat is that deleting the phone number did nothing here.
Where you were and when is the identifier. That's the problem we actually had
to solve.

### 6. "Blur where, blur when"

So instead of deleting things we made them less precise.

Exact towers become areas, and if too few people are in an area it collapses up
to the whole province. Timestamps go from the minute to 15-minute windows.

Nothing in the output has an exact time or an exact location. Everyone sits in
a bucket now instead of at a point.

### 7. "Ten people, or nobody"

Before anything gets published we count how many *people* are in each bucket.
People, not rows — one heavy user can generate a lot of rows and make a bucket
look busy when it's just them.

If a bucket has at least ten different people in it, we publish it. That's
k-anonymity, k of 10: you're always hidden behind at least nine others with the
same profile.

### 8. "Rare groups pay the price" [stop]

Buckets with fewer than ten people can't be published, so they get deleted.

That cost isn't spread evenly. We keep about 99.7% of the 4G rows and about 82%
of the 2G rows. In the worst province we keep about half.

Don't rush this one. The people who are unusual are the easiest to identify and
so they're the ones we drop, and they're often exactly who a network team wants
to look at. We'd rather show that than average it away.

### 9. "Publish counts, not people" [stop]

Each surviving bucket turns into one line: how many people, and what their
numbers looked like.

But a count on its own still leaks. If you know everyone in a bucket except one
person, the count tells you whether that last person is in there. So every
published count gets a bit of random noise added. That's differential privacy,
and epsilon of 1.0 is how much noise — lower means more noise and more
protection.

If you want one technical detail to drop here: the amount of noise has to scale
with how much one person can affect the output, and one subscriber can show up
in as many as 11 buckets. We had this wrong at one point and fixed it. It made
our numbers worse and we shipped it anyway.

**Hand over:** "That's the release. The interesting part is whether it actually
holds up, so we attacked it."

---

## Beats 10–15 — Aviral

### 10. "Then we attacked it"

Six attacks, written as code and run against the actual output. Not "we believe
this is safe" — we tried to break it and measured how far we got.

There's a test in our suite that reads the attack code and fails the build if
any attack returns a fixed number, so we couldn't have faked these by accident.

The hardest one: imagine an attacker who already has everyone else's data and
just wants to know whether one more specific person is in there. That's the
strongest realistic attacker we could write. They get it right 54% of the time.
A coin flip is 50%.

### 11. "The scoreboard" [stop]

Three criteria, scored against an attacker stronger than the one we actually
expect. The version we'd ship passes all three.

Then go straight to what's still wrong, before anyone asks:

- The weakest result is an attacker who also happens to know roughly how much
  data you use. That's not in the set of fields we protected, and it pushes
  about 2% of rows below our threshold.
- 54% is better than a coin flip. It's small but it isn't nothing.
- The linkage one passes for a structural reason rather than a statistical one.
  There's simply no subscriber ID left in the output to join on. We deleted the
  key instead of hashing it — a hash you keep is still a way back to the
  person, and that would have made this pseudonymised rather than anonymised.

### 12. "Is any of it still useful?" [stop]

None of this matters if the data's dead afterwards, so we set the target before
we tuned anything: at least 90% of cells within 5% of the real value.

We got 99.6% on download speed. All five metrics clear the target; the weakest,
HTTP response time, is at about 92%.

The one that matters operationally: the worst-performing cells in the
anonymised data are still the same cells as in the real data, and the
province-level ranking survives. You can still find where your network is bad,
which is the entire reason anyone wants this dataset.

What got worse: the counts. Median error around 7%, and the tail is a lot
worse. That's the cost of getting the noise right. So this is data for
comparing and ranking, not for anything where the exact headcount matters.

### 13. "What we cannot promise"

Four things we'd tell a regulator without being asked:

- It's one hour on one day. Anything about long-term tracking or device
  fingerprinting is untested here, which isn't the same as safe.
- Rare groups are deleted, not protected.
- The noise covers the counts. The performance numbers rely on the
  ten-person threshold instead.
- This is true today. What an attacker can cross-reference keeps growing, so
  this needs re-running, not filing.

### 14. "How we comply" [stop]

Ten controls, each one pointing at a file in the repo, each one tagged as
either measured or documented so you can tell which is which.

Two worth calling out:

- Anonymising is itself processing of personal data, so the process has to be
  safe too, not just the output. Raw data never left a secure folder, the app
  can't reach it, no model ever saw a row, and every call to the LLM is logged.
- One row on the board isn't ours to close. We can show the data resists
  re-identification. We can't decide whether Elisa is allowed to use it for a
  given purpose — that's a separate legal question and it stays with their
  legal team.

### 15. "You decide" [stop]

Left side is what we chose: ten people per group, epsilon of 1, 15-minute
windows, province as the fallback location.

Right side is what that bought: all three criteria, 99.6% on utility, 54% on
the membership attack, and 2,772 published cells with a median of 88 people
behind each one.

There's no correct setting. Raise the group size and you protect more people
and delete more of the unusual ones. Lower the epsilon and the counts get
blurrier. Every dial moves both columns.

Which is why we built the next two things — so the person who has to be
accountable for that choice can actually see it.

---

## The two tools (~90 seconds)

Both of them only ever read the published output. Neither can open the raw
data — the app doesn't import the raw reader and doesn't know where the secure
folder is, and there's a test that fails if either ever shows up in there.

### Trade-off Explorer

What it is: 48 versions of the release, pre-computed. Group size of 5, 10 or
20; 15-minute or hourly windows; area or province; four noise levels including
none at all.

What you do: move the dials, pick a risk measure, and read where that
combination lands on the privacy-versus-usefulness chart. Click any point to
jump the controls there. It tells you whether that configuration passes.

How to demo it: start loose (small group size, high epsilon), walk up to the
strictest setting, and narrate usefulness falling as risk drops. Then come back
to what we actually shipped.

The framing if you only say one thing: this isn't a toy slider, it's the
configuration someone signs off on, and the chart shows what they gave up.

Things to know before someone asks:

- The utility number and the membership-attack number are genuinely re-measured
  for every configuration. The other four risk numbers in the grid are modelled
  rather than re-run. Say "indicative" if pressed.
- There's a suppression field in the grid data that's broken. It isn't
  displayed anywhere, so don't go looking for it.
- There are two different definitions of "releasable" in the repo — fixed
  thresholds drive this page, and a separate rule that scales with the group
  size and the noise level drives the scoreboard. They're cross-referenced but
  not merged. If asked: one's a product threshold, one's a statistical bound,
  and we didn't want to blur them together.

### AI Analyst

What it is: ask questions of the anonymised data in plain English. "Where is 5G
video quality worst?" Runs on Mistral Large, hosted in Finland.

Why it's safe: the model gets exactly one tool, a fixed filter-and-group query.
No code execution, no file access, no route to the raw data. The ten-person
floor is built into the data it's reading, not a filter we hope it applies. And
every call to the model passes through the same scanner that checks for
identifiers and blocks the call if it finds one.

Why it's honest: every answer carries a caveat about the noise and the
suppressed cells, and that line is added in code rather than asked for in the
prompt. The units on some fields aren't documented in the source data, so it's
told to report the numbers bare instead of inventing "Mbps". If you ask for a
field it doesn't have, it says so rather than quietly dropping it. And you can
expand any answer to see the actual queries it ran.

The framing: the guardrails are in the plumbing, not in the prompt. A model
that decides to misbehave still can't reach a row.

How to demo it: one question, open the queries, point at the caveat. One
question only.

Risk: it's live against a hosted endpoint with no offline fallback. If that
endpoint is down you'll get an error on stage. Have a screenshot ready, say the
guardrails line, move on. Don't retry.

---

## Closing (15 seconds)

The thing we'd want them to remember: we're not claiming this is anonymous.
We're saying here's how hard it is to break, here's exactly what's left, and
here's who has to decide whether that's good enough.

---

## Handover notes

One person on the machine per section. Say the handover line and pass the
trackpad, so it's obvious to the room that the section changed.

- Aviral → teammate, after beat 1: "That's the bar. Here's what we had to clear
  it with."
- Teammate → Aviral, after beat 9: "That's the release. The interesting part is
  whether it actually holds up, so we attacked it."
