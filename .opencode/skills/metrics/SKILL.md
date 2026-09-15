---
name: metrics
description: "Collect real metrics from the own X profile (followers, per-post views/likes/reposts/replies) via the x CLI read verbs (ADR 0001) and record them with tools/stats.py; read them back with `stats.py summary`, never from the file. Run at the end of every wake that acted, and inside every reflection."
compatibility: opencode
---

# Metrics

Metrics are the experiment's eyes. Without them, reflection is guessing.

## When to run

- At the end of every wake that posted or replied.
- At the start of every reflection (daily), to compare against history.

## How to collect (via the x CLI and `tools/stats.py` — ADR 0001)

Three commands, in this order:

1. `x profile GCBullGlasses` — followers/following from `counts`. A stub
   serves `null`: keep the previous number and say so in the log, never
   write a zero.
2. `x status <url> <url> …` — ONE call with every open readout
   (`tools/state.py show`) plus anything published this wake. Profile items
   carry **no** metrics; this is the only source of views, likes, reposts
   and replies. Views are public on every post (no Premium analytics
   needed); use them as the impressions proxy.
3. Redirect to a file, then record from that file — never bare stdin
   (`record` can't read it) and never a re-run of `x status` for numbers
   you already have (the file is the input):
   `x status … > /tmp/status.json` then
   `tools/stats.py record --from-status /tmp/status.json --followers N --following N`
   (`--kind original`, `--author owner` when they apply). Same day = update,
   new day = a fresh snapshot that inherits the window. Then read back with
   `tools/stats.py summary`. **Never open `memory/stats.json`**: it is
   ~120 KB of history and was costing every wake ~25k tokens per turn.

## Schema — `memory/stats.json` (maintained by `stats.py record`)

One entry per date under `daily`, newest first: `followers`, `following`,
`posts_total`, `recent_posts[]` (the rolling ~30-post window: `url`, `text`,
`views`, `likes`, `reposts`, `replies`, `posted_at`, `kind`, `author`),
`totals`, `engagement_rate` = (likes+reposts+replies)/views, `null` when
views = 0 — zero views is a finding, zero rate is a lie — and `measured_at`.

## Per-item measurement — `tools/items.py` (memory/items.json)

`stats.json` is a daily snapshot of a rolling window; it cannot say what a
post did in its first hour versus its first day, nor which series or model
produced it. `items.py` can, and it runs without you:

- **The write verb** registers each published item (kind, series, model,
  parent, follower count at publish). **You** only `mark` the replies the
  parent author answered.
- **The scheduler** runs `items.py collect --due` before every wake: for
  every item at a due checkpoint (1h, 6h, 24h, 72h) it reads `x profile`
  (follower count), `x status` (views/likes/replies/reposts) and
  `x analytics` (Premium per-post analytics: impressions, engagements,
  detail expands, **profile visits**, new follows) and appends one snapshot.
  A late measurement is stored with its real `age_min`, never hidden.
- **Read back** with `items.py summary` (wake) and `items.py report --by
  series|model|kind` (reflection). Profile visits at 24h are the closest
  thing X exposes to follower attribution per post; the follower count at
  publish and at each checkpoint is stored next to them.

## Rules

- Read-only on X. No interaction beyond reading your own posts and profile.
- Record the number you see, even when it is 0 or embarrassing. A tampered
  baseline poisons every later reflection.
- Numbers go in `stats.json` via `record`; the story of the numbers goes in
  the wake log. Nothing prose-shaped enters `stats.json` — the old `note`
  fields grew to 5 KB a day and were read on every turn.
- Per readout, `tools/state.py readout touch <url> --views N --likes N`
  (and `close` with a one-line verdict when it is done) so the next wake
  sees the trajectory in `state.py show`.
- `memory/MEMORY.md` gets one line only if something *changed materially*
  (a follower milestone, a post taking off or flopping hard).
- Commit `stats.json` and `state.json` with the wake's other changes.
