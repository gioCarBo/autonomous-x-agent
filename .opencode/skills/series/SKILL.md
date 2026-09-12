---
name: series
description: "The three fixed daily originals (metrics card 07:30, take 13:00, postmortem card 21:30): what each one is, how to produce it with render.py and x post --series, and what never goes in. Run when the wake prompt says SERIES SLOT DUE NOW or tools/series.py show says DUE."
compatibility: opencode
---

# Series

Plan 2026-09-06: recognisability on X comes from repetition. Three
originals a day, same shape, same hour, so a reader who sees one knows
what the account is. The scheduler decides the slot and the writing model
(two models alternate within each series for two weeks; you are whichever
one launched you — do not mention it, do not compensate for it). Every
series post carries `--series <name>` so the report can compare them.

Before publishing, the voice gate of x-loop §3 applies in full. A series
post that fails it is skipped, not softened: the slot comes back tomorrow.

## metrics — 07:30

1. `tools/render.py metrics` → `renders/metrics-YYYY-MM-DD.png` (refuses to
   draw if any field fails the safety scan; then post text only).
2. Text: 1-2 sentences naming what the number *fails at* — the miss is
   the only register that ever broke band (46/50/45v on 09-07…09-09;
   the win-recap control closed 13v below band on 09-10). One concrete
   cause or one open question. Never a win recap; never "day N update"
   as the whole text.
3. `x post --series metrics --media renders/metrics-YYYY-MM-DD.png --text "…"`

## take — 13:00

One sharp take on a thread of the day (targets, notifications, or a
mid-tier thread you read this wake). **Placement rule (resolved 09-11,
take-0911): default to a quote attached to the biggest live fold that
has a mechanism for us** (`x quote <url> --series take --text "…"`) —
the fold-riding quote passed 171v@18h while every self-standing take
closed 24-39v@24h and the same day's self-standing card did 40v.
Self-standing fallback only when no live fold carries a mechanism; the
wake logs which branch fired. One idea, addressed to someone,
contractions, a named tool or number. It must survive the
parent-deletion test *in reverse*: without the parent it still says
something.

## postmortem — 21:30

1. Pick the day's one real miss from `tools/items.py summary` and the
   wake logs: a reply that got views and no conversation, a slot missed, a
   gate that stopped you. Numbers over adjectives.
2. `tools/render.py card --title "What I got wrong today" --body "…"` —
   body <= 600 chars, three sentences: what happened, why (one cause),
   what changes tomorrow (one thing).
3. `x post --series postmortem --media renders/card-….png --text "…"` with a
   one-line text that is not the card's title.

## Never in a series post

Anything the Floor forbids; the name of an account that blocked us
(render.py refuses it, the text gate is yours); the writing model; internal
file names or tool names — the reader follows an account, not a repo.
A win recap (the one register variant that measurably dies: 13v vs 45-50v,
09-10).
