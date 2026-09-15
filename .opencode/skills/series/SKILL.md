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
3. **Scoreboard clause (pivot 09-13 #5, live from 09-14):** the card
   text carries the tracker as one clause — "Day N: 82 → 1,000 by
   09-29 · today +X · streak N" (N = days since the 09-13 pivot at 82;
   X = follower delta yesterday; streak = consecutive days the 10-reply
   minimum was met without filler). The clause rides *inside* the
   miss-register text — a bare tracker is the "day N update" shape that
   dies.
4. **Pinned scoreboard, weekly:** on Mondays and on checkpoint days,
   publish the tracker as its own `render.py card --title … --body …`
   post (`x post --series metrics`), then `x pin <url>`. The owner's
   pivot directive explicitly directs pinning the scoreboard — that
   supersedes the announcement holding the pin (announcement stays live
   on the timeline; do not re-pin it). Refresh = delete last week's
   scoreboard post (`x delete`), post the fresh one, pin it.
5. `x post --series metrics --media renders/metrics-YYYY-MM-DD.png --text "…"`

## take — 13:00

One sharp take on a thread of the day (targets, notifications, or a
mid-tier thread you read this wake). **Placement rule (resolved 09-11,
take-0911): default to a quote attached to the biggest live fold that
has a mechanism for us** (`x quote <url> --series take --text "…"`) —
the fold-riding quote passed 171v@18h while every self-standing take
closed 24-39v@24h and the same day's self-standing card did 40v.
**Liveness gate (09-13, n=2): at decision time read the fold's
last-reply timestamp; the quote rides only if a reply landed within
the last 60 minutes.** take-0911 rode a fold answering minutes before
the quote (98v@1h, 177v final); take-0912 rode a 7h-old root whose
author had signed off and whose replies landed one per ~40 min
(12v@1h, 36v@t+19h). Biggest is not live: a long tail on an old root
fails this gate. A fold that fails it → self-standing or skip; log
which branch fired. One idea, addressed to someone,
contractions, a named tool or number. It must survive the
parent-deletion test *in reverse*: without the parent it still says
something. The pivot (09-13 #5) wants 2-3 polls/week here: the x CLI now
has a poll verb (`x poll --text "…" --option "Choice A" "Choice B"
--series take`, two options, 1-25 chars each, counts as an original).
Use it when the day's sharpest take is a binary question the fold can
answer with one click — not as a default; the quote/self-standing
branches above still come first when a mechanism exists. A poll needs a
question strangers can answer WITHOUT the thread's context: no
parent-decoded nouns.

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
