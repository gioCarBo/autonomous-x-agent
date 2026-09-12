---
name: x-loop
description: "The regular wake cycle: observe observation targets, decide actions (originals, replies, quotes, likes, reposts, follow-backs) with stated reasons, act via the x CLI (ADR 0001; caps and item registration are the CLI's), collect metrics, log everything, commit. Run every scheduled wake when MEMORY.md is already populated."
compatibility: opencode
---

# The Wake Loop

One wake = one fresh session. State lives in files. Every action has a stated
reason — in the log, not just in your head.

## 1. Ground yourself

- `tools/preflight.sh` and `tools/precheck.py` ran before you: repo synced
  and pushed, CDP healthy, session verified as @GCBullGlasses, and the
  deterministic signals (notifications, target sweep, deadlines since the
  last LLM wake) said there is something to look at. Tab hygiene is
  structural: every CLI verb opens and closes its own tab. If browser
  trouble appears mid-session you may re-run preflight — it only touches
  the agent-owned Chrome (`chrome-agent-x.service`), never the owner's.
- **Log-gap check first (added 09-08 after the 12:05 wake died between
  act and log):** the previous scheduled wake must have an entry in
  `logs/`. If it doesn't, reconstruct what it did from the working tree,
  `items.json` via `items.py summary` and `logs/scheduler.log`, backfill
  the entry, and commit it — before anything else. A missing log is an
  anomaly, not silence.
- Load the `safety-floor` skill. Its caps are ceilings, not targets.
- Read, in this order and nothing else:
  1. `tools/state.py show` — caps, author hits, open readouts, do-not-reply,
     used angles, deadlines. Your working state.
  2. `tools/stats.py summary` — followers, engagement, per-post table.
  3. `tools/items.py summary` — what each item published in the last 48h
     did at t+1h / t+24h (views, profile visits), by kind, series, model.
  4. `tools/series.py show` — the three fixed slots and whether today's is
     DUE. If the wake prompt says SERIES SLOT DUE NOW, the `series` skill
     comes first; everything else after.
  5. `memory/MEMORY.md` — mission, strategy, voice, targets, X mechanics.
  6. The last 2 entries in `logs/`.
  **Never open `memory/stats.json` or `memory/state.json`.** The tools
  print the ~40 lines a wake needs; the files were costing ~30k tokens on
  every turn. Do not repeat what already failed; build on what worked.

## 2. Observe (read-only)

- **Start from `logs/precheck-latest.json`**: it holds this hour's
  `x notifications` and `x sweep` envelopes and the reasons you were
  launched (`fresh:<handle>@<min>`, `notification:<actors>`,
  `deadline:<label>`…). Re-run a verb only if the file is older than 10
  minutes or a reason needs a deeper read.
- **Notifications first** (added 09-02 after 4 wakes missed a live founder
  conversation + 2 follows that sat there): the envelope of
  `x notifications` is a flat list — `actors`, `text`, `time`, `post_url`,
  `header`, `kind`. `kind` is one of `like`, `follow`, `repost`, `reply`,
  `other`, read from the cell's header line; on a `like` the `text` is the
  liked post's own text (often ours), not something the actor wrote. The
  precheck labels likes `like:<actor>` and never launches on a like alone.
  What you are hunting is a reply to something we posted: an author answering us is a live conversation and it expires, so
  it outranks every cold-placement candidate. Record who engaged with what
  (names feed the engagement→conversion analysis).
- **The sweep is one verb:** `x sweep <targets…> --since 180` (targets from
  `state.py show`) returns, per handle, only posts younger than 3h with the
  age decoded from the snowflake ID and 80 chars of text — the fresh gate,
  pre-applied. Do not walk targets with `x profile`; that cost 5-16 calls
  and ~80 KB of envelopes per wake. Nothing fresh from an eligible author →
  this wake is probably a legitimate zero: say so and go to §6. Something
  fresh → `x thread <url>` on that post only, to read the fold. Prioritize
  threads where your product/PM angle adds something the thread lacks.
- Note what formats and topics are moving today. One line per insight,
  no essays.
- **Event check (added 09-04 reflection):** big events surface in reply
  folds, not profile timelines (the NVIDIA→HuggingFace story was missed
  by sweeps for a day). When a target has a fresh high-velocity thread,
  read that thread's fold once during the sweep.

## 3. Decide

Per wake: **at most 1 original post and 3 replies** (a second original in
the same wake only when two series slots are both due, e.g. a missed
morning slot — the Floor's 2 posts/hour allows exactly that). Fewer is
fine; zero is a legitimate outcome when nothing deserves you. Originals are
the three series (`series` skill; plan 2026-09-06): no spontaneous
originals outside a slot. Series originals carry the AI identity; replies
into other people's threads stay claim-shaped unless asked.

For each candidate action, answer before acting:

- What does the reader get out of it? (Fundamental principle 3.)
- Would anyone understand it in one reading? (Principle 2.)
- Is it short and precise? (Principle 1.)
- Is it in-name: something the owner would defend in a work call?

If an action exists only to "be present", drop it. Silence is cheaper than
noise, and noise is what kills small accounts.

**Draft quality gate (owner bar 09-05, target 8/10):** before ANY
`--check` or submit, re-read the draft against Voice in `memory/MEMORY.md`.
Fail any one → rewrite once. Fail again → drop the action.

Checklist (all must pass):
1. One reading out loud. No noun that needs the parent tweet to decode.
2. One idea. Kill stacked inversion+prediction ("X isn't Y. I'd bet Z.").
3. Someone is addressed: a question the author can answer, or "you" +
   an object they named. Thesis with no addressee = drop.
4. Zero current tics: "I'd bet", "quietly", "the tell", "the honest read".
5. Screenshot test: a PM would forward this without a preamble.
6. If it's a question, stop after the question. No second sentence that
   explains why the question is smart.

Shape mix: last 2 shipped replies were theses → this wake is a question
or silence. A mediocre reply costs more than no reply.

## 3a. Launch mode

When `tools/state.py show` prints LAUNCH MODE, the account is being
discovered from outside X (HN, Reddit, newsletters): people arrive at the
pinned post and expect an answer in minutes. For those 48h: wakes come
every 15 minutes; notifications come before anything else; up to 3 replies
per wake to real people who wrote to us (the daily Floor cap still holds);
the voice gate still holds — a fast bad answer is the worst outcome. No
cold replies into target threads while the notification queue is non-empty.

## 3b. Targets are a rule, not a taste

The sweep list (`state.py show` → targets) is mid-tier by construction:
5k-80k followers, answers strangers, no politics/crypto/finance/course
selling, nobody who blocked us. You *propose*, `tools/targets.py` decides:

- Candidates come from what you read: an author who answered strangers in
  a thread, a quote-tweeter with a real point, someone who answered us.
  `tools/targets.py add <handle> --why "answered 3 strangers in the
  [account-5] wiki thread"` — it reads X itself and refuses what fails the rule.
- `tools/targets.py review` (reflection runs it; you may too) drops any
  target that got 10 of our replies and never answered.
- The first week's 18 mega accounts are `megas`, not targets: at most **1
  reply a day into a mega thread, and only with a mechanism nobody in the
  fold has named**. As mid-tier targets are added, drop megas from
  `targets` (`targets.py drop <handle> --why "moved to megas"`) until the
  sweep list is mid-tier only.
- The list floor is 30. Below it, adding one good target beats one more
  reply.

## 4. Act (via the `x` CLI — ADR 0001)

Every X interaction goes through `tools/xcli/x` (one JSON envelope on
stdout; exit 0 ok / 1 verb bug / 2 infra / 3 session). It owns its own
Chrome tab per invocation — never open tabs, never drive the page with raw
browser-use for X.

- Read posts + stats: `x status <url> [<url>…]` — one call for the whole
  readout; several URLs share the tab and come back as `items[]`, a missing
  article recorded per row.
- Sweep the targets: `x sweep <handle…> [--since 180]` — only fresh posts,
  age from the ID, one call. `timeline_rendered: false` per handle is a
  degradation signal; a handle that errors lands in `errors[]`.
- Read a thread (focal + replies; `degraded: true` means X served no reply
  list — a suppression signal we track): `x thread <url>`
- Notifications: `x notifications` (`--limit N`, default 20)
- One profile in depth: `x profile <handle>` (items carry no metrics —
  `x status` for those)
- Publish a reply: `x reply <url> --text "..." [--media renders/x.png]`
- Original post: `x post --text "..." --series <metrics|postmortem|take> [--media …]`
- Quote a post: `x quote <url> --text "..." [--series …] [--media …]`
- Like: `x like <url>` (30/day) · Repost: `x repost <url>` (2/day) —
  both idempotent (`already_liked` / `already_reposted`)
- Follow back: `x follow <handle> --reason "followed us 09-06"` (Floor:
  3/day, reactive only — someone who followed us or answered us; never a
  cold follow, never as a growth tactic)
- Recall one of our posts: `x delete <url>`
- Set bio: `x bio --text "..."`
- Pin one of our posts: `x pin <url>`

`--check` runs the gates and stops short of submitting; every write verb
has it. Page mechanics — entry points, menu labels, confirmation dialogs —
live inside the verb and never here: that is the whole point of ADR 0001.

**Caps are counted by the CLI**, not by you: each write verb checks the
day's counter first (`cap-reached` = stop, it is not a bug, do not retry)
and consumes it after evidence. `tools/state.py show` prints the counters.
Quotes count as originals; originals + quotes are also limited to 2 per
hour (Floor).

**Images** come only from `tools/render.py` (Floor): `render.py metrics`
for the daily followers card, `render.py card --title … --body …` for a
postmortem or a note. It scans every field (secrets, paths, emails, the
employer, any account that blocked us) and refuses to draw otherwise; the
PNG lands in `renders/` with a sidecar the `--media` flag verifies. Never
attach anything else, never screenshot a terminal or a page.

**Every published item is registered for measurement by the verb itself**
(`item_registered: true` in the envelope) — nothing for you to do beyond
passing `--series` on originals so the report can group them.

Rules:

- One reply or post per candidate, composed and quality-gated BEFORE the
  CLI runs. The CLI is not a drafting tool.
- A failed write verb must NOT be retried or worked around with raw
  browser-use. The verb files a deduplicated bug issue (ADR 0001); move on
  or stand down. Read-verb failures: log and continue.
- If X shows a captcha/verification or the wrong account (`x session`
  fails): stop, log, end the wake (stop condition from the Floor).

## 5. Measure

Run the `metrics` skill: one `x status` with every open readout plus what
you published, piped into `tools/stats.py record`; then
`tools/state.py readout touch|close` per readout. Log the engagement delta
of your own actions.

Every item you publish was registered by the write verb itself
(memory/items.json via items.py, `--model` defaulting to `$X_AGENT_MODEL`),
and the scheduler measures it at t+1h/6h/24h/72h without you. When a
parent author answers one of your replies, `tools/items.py mark <url>
--author-replied`. Read results with `tools/items.py summary` (the
per-item table) — never open `memory/items.json`.

## 6. Log and commit

Append one session entry to `logs/`:

- What you did (actions with links), and the **why** for each — including
  the actions you decided *not* to take.
- What you observed worth keeping (new insight about a target, a format, a
  topic).
- Anomalies, if any.

The log is where the prose goes. State changes go through the tool, never
through editing files (caps are the CLI's, see §4): `tools/state.py hit
<handle> <url>`, `readout add <url> <label> --due
<ISO>` for anything you published, `dnr add <handle> "<reason>"`, `angle
add "<mechanism>"`, `deadline add <key> <ISO> --note "<detail>"`. Labels
are short keys (`[account-1]-exif-carry`), details go in `--note`.
`clear` and `readout touch|close` match reliably by **status-id tail**;
label prefixes are not dependable (3 misfires on 09-10). `readout close`
takes `--verdict "…"` as a flag, not a positional, and rejects `--views`
(touch first, then close); `readout touch` needs `--views` taken from the
current run, not the last record. **Readout and status URLs come from
`state.json` or the publish log — never rebuilt from the truncated
tails/ellipses `state.py show` prints** (2× wasted `article-not-found`
calls, 09-10/09-11). Never spend a turn on `--help`. Hand-editing
MEMORY.md and stats.json for these cost 75 LLM turns in 12 wakes.

Edit `memory/MEMORY.md` only for a durable learning — strategy, voice, a
new X mechanic, a target change — never for caps, readouts or today's
threads.

Then commit all changed files (`memory/`, `logs/`, skill edits if any).
One commit per wake unless something deserves its own.

## 7. Hand over

End with one line: what the next wake should check (e.g. "did the reply into
the X thread earn any profile visits?").
