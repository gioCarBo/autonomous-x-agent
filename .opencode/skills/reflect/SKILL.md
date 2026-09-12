---
name: reflect
description: "Deep daily reflection: read `tools/stats.py summary`, `tools/state.py show` and the judged day's logs, judge what worked and what didn't, evolve strategy, skills, and memory accordingly, commit with a message that states the learning. Run once per day at 06:30, before the first wake: it judges the calendar day that just ended."
compatibility: opencode
---

# Reflection

Wakes act. Reflection judges. Once a day, look at the evidence and change
what the evidence says to change. This is how the experiment compounds.

You run at 06:30, before the first wake, so the day under judgement is the
one that just ended — while the log is named for the date you run on
(`2026-09-05-reflect.md` judges 09-04). Read "today" below as that judged
day.

## 1. Gather evidence

- Run the `metrics` skill first if `tools/stats.py summary` flags a stale
  measurement — reflection runs on fresh numbers.
- Read `tools/stats.py summary --days 7 --posts 20`, `tools/state.py show`,
  every log entry of the judged day, and `memory/MEMORY.md`. Never open
  `stats.json` or `state.json` directly.
- Per item: `tools/items.py report --days 14 --by series`, then `--by
  model` and `--by kind`: median views at 1h and 24h, likes, replies,
  profile visits, how many replies earned an author's answer. This is the
  evidence for the series and for the two-week model A/B — read it, do not
  re-derive it from logs.
- The owner's ratings: `tools/rate.py show --days 14` (1-10 per post with
  a line of why, by model when both arms are rated). A rating below 6 on a
  shape you repeated is a voice finding, not noise.
- `tools/targets.py review` — applies the drop rule, prints the list
  against its floor of 30; `tools/series.py show` — which slots were
  missed yesterday and why (the wake logs say).
- For each action taken (post/reply), record outcome: views, likes, replies
  earned, any profile follows it produced. Compare against the account's own
  baseline, not against big accounts.

## 2. Judge honestly

Answer in writing (the reflection log):

- What worked, relative to baseline? Be specific: which thread, which angle,
  which format.
- What flopped? Same specificity. A flop with a plausible cause is data.
- Which open questions in MEMORY.md did today's data move? Move them:
  promote an answer to a decision, kill a question the data has made moot.
- What did *not* get tested that today's setup made cheap to test next?
- The plan (docs/plan-2026-09-1000-followers.md) is frozen between its
  checkpoints (`state.py show` → deadlines): judge content, series text,
  targets and voice freely; do not re-open strategy, cadence or identity
  before a checkpoint date. If the evidence screams, write it down for the
  checkpoint.

Do not invent lessons from one data point. With small numbers, prefer
"signal worth watching" over "lesson learned". A real lesson needs either a
clear cause or repeated pattern.

## 3. Evolve (within the Floor)

Change only what evidence justifies:

- `memory/MEMORY.md` — prune stale content, update open questions, sharpen
  strategy notes. This is the file the next wake reads; keep it lean and
  durable. Working state (caps, readouts, do-not-reply, used angles,
  deadlines) lives in `state.json` through `tools/state.py`: close what is
  finished (`readout close`, `dnr clear`, `deadline clear`) rather than
  narrating it here.
- Your skills (any except `safety-floor`) — if a procedure repeatedly
  misfired, fix the procedure, not just the plan.
- Strategy — voice, cadence, targeting. Evolution is allowed; the Floor and
  the Fundamental Principles in AGENTS.md are not negotiable.

Deliberate bias: favor experiments that produce *distinguishable* results
(two formats that can't both win teach nothing; two that can't both lose
teach nothing either).

## 4. Write the reflection log

One entry per day in `logs/` (`YYYY-MM-DD-reflect.md`):

- The judgment (§2), in plain sentences.
- The changes made (§3), each with its one-line justification.
- Tomorrow's single most important question.

## 5. Commit

One commit for the whole reflection. Message = the main learning, not
"daily reflection".
