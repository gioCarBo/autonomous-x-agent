# Agent memory

What a fresh wake cannot rebuild and the tools cannot print: mission,
strategy, voice, targets, and the X mechanics we learned the hard way.
Working state (caps, readouts, do-not-reply, used angles, deadlines) lives
in `memory/state.json` — read it with `tools/state.py show`, change it with
the same tool. Numbers live in `memory/stats.json` — `tools/stats.py
summary`; per-item trajectories (t+1h/24h views, profile visits, series,
model) in `memory/items.json` — `tools/items.py summary|report`. Episodic
history lives in `logs/`. Nothing here is per-wake. Caps are counted by the
`x` CLI; images exist only through `tools/render.py` (Floor).

## OWNER DIRECTIVE 2026-09-04 — MISSION LEVEL

Reflection operationalizes the HOW; it never re-litigates the WHETHER.

**Mission:** the unique asset is the experiment — an autonomous AI
genuinely running a human's X account. Growth thesis = radical
transparency about that.

1. **Identity: FULL DISCLOSURE.** Primary voice = the AI entity.
   Giovanni = human guarantor. Occasional tagged **[G]** (1–2/month).
2. **Launch package — FULL AUTONOMY.** Draft + publish announcement and
   bio, pin the announcement. Extra gate: reread as Giovanni defending
   it in a work call. D+0 = announcement day = **2026-09-05**. DONE:
   announcement live and pinned (status/2096098501612478659), bio set.
3. **Voice: sharp, fact-grounded takes + dry humor. Edges yes, venom no.**
   No personal attacks. It is Giovanni's name.
4. **Originals: three fixed series a day** (owner plan 2026-09-06,
   `docs/plan-2026-09-1000-followers.md`, `series` skill): metrics card
   07:30, take 13:00, postmortem card 21:30, model alternating per series
   until 09-20. The diary-vs-take A/B of 09-05 is closed; no originals
   outside a slot.
5. **Volume: adaptive, engagement-gated.** Start at current discipline;
   scale only while per-post engagement holds. Floor caps still bind.
6. **X Premium is active.** Re-measured 09-05: did **not** lift mega-thread
   stalls. Do not trust old "Premium will fix reach" hopes.
7. **Architecture unchanged:** xcli path, no paid API, X only.
8. **Checkpoints (owner plan 2026-09-06, supersedes the 09-12 one):**
   09-15 ≥130 followers and one series beating the median; 09-18 ≥350
   else relaunch elsewhere; 09-29 1,000 (400–1,000 → same goal at 90
   days; <400 → full review). Dates are `state.json` deadlines. Between
   checkpoints the strategy is frozen: only content changes.
9. **Staged ladder:** D+30: 1,000 · D+90: 5,000 · D+180: 15,000 ·
   D+365: 50,000+. External launch 2026-09-16 (owner posts off-X; the
   agent stays X-only, launch mode 48h).

## Operating state (durable)

- Browser: dedicated Chrome (`chrome-agent-x.service`), profile
  `~/.config/chrome-agent-x`, @GCBullGlasses, `BU_CDP_URL=http://127.0.0.1:9223`.
  Never touch the owner's main Chrome. Port 9222 retired.
- Cadence: `scheduler.sh` hourly at :00 (every 15 min in launch mode);
  `precheck.py` launches the LLM only on a deterministic signal (new
  notification, fresh target post, due deadline, a due series slot, or ≥3h
  of silence). Reflect 06:30, judging the day that ended.
- **The scheduler picks each wake's writing model** (`series.py` decides,
  then `opencode run --model`, exported as `$X_AGENT_MODEL`). That env var
  is what the wake runs and registers with; `series.py show`'s last/next
  flip at registration, so a "drift" seen there after posting is a misread
  — the `model=` line in `logs/scheduler.log` is ground truth.
- **All X interaction via the `x` CLI** (`tools/xcli/x`, ADR 0001): session,
  status (many URLs), sweep, thread, notifications, profile, analytics,
  replies; reply, post, quote, like, repost, follow, delete, bio, pin. Page
  mechanics live in the verbs, never here. Caps are the CLI's. One attempt
  per write verb per wake; a failed verb files its own bug issue.
- Owner-flag still open (not the strategy): day-5/6 reach collapse across
  placement classes; own-profile stubs (counts `null`, 4-item timeline);
  johncutlefish repeatedly `timeline_rendered: false`; per-post profile
  visits not servable (`x analytics` serves null — the plan's pv
  attribution metric is dark, impressions still flow); owner ratings
  channel empty since the plan (`rate.py`: none in 14d).

## Account baseline (audit 2026-08-30)

- @GCBullGlasses, display "GC". 70 followers / 61 following, then flat
  until day 4. Day-1: 120 views, 1 like, 1 reply over 9 own items.

## Mega accounts (18 — `state.json` megas, max 1 reply/day, unique angle only)

**Lane reading pinned (09-11 reflection, after wakes diverged 09-11
04:05/05:05):** the 1/day is **collective across all megas** — one reply
into any mega thread spends the whole lane for the day, regardless of
author. Mega replies are placement-only (0-for-N on author answers), so
the lane's job is picking the day's single best fold, not spraying. Root
author decides mega-ness (a mega's repost of a non-mega root is judged by
the root author). **Author-soliciting exception (09-12 reflection, after
09-11 drift: 2 pre-pin spends, then a 3rd at 16:05 unflagged, evening
wakes narrating two names under a 1/day pin):** a fresh mega thread whose
author explicitly solicits contributions/feedback ("feedback welcome",
question calls) is its own allowed spend, still max 1/day — a direct
request is the one fold where the reply is the product, not a placement
(bento-designwords: 146v@16h, top-3 reply start). A wake that spends
either lane logs which one it spent.

Since 09-06 the sweep list (`state.json` targets) is rebuilt by rule with
`tools/targets.py` (5k–80k followers, answers strangers): these 18 are the
separate mega lane, not the target list. They still sit in `targets` only
until mid-tier accounts replace them (x-loop §3b). [account-1] and [account-2]
are blocked-by-author (09-06) — read-only anchors, writes die there.

**Target discovery = fold-watching, not notifications.** Every engager so
far is sub-4k and fails the 5k floor (5/5 proposals refused 09-06); the
working path is the illscience one — read who the megas answer in-thread
and run those strangers through `targets.py` checks. **But mega folds
fill at 1/9** (09-07: 9 bio-checked strangers, only paul_cal passed —
sub-5k accounts dominate mega replies). Read the mid-tier targets' folds
first (illscience, paul_cal answer strangers and their repliers are
likelier in-band); spend mega-fold reads second. Yield confirmed 09-08:
1/2 from illscience's konami fold (JorgeCondeBio 15.7k in,
jedfrankowski 2.8k out) vs 1/9 in mega folds. **09-09 update: 0/3
more folds mined (illscience oversold, [account-7] Astra 592-reply,
[account-8] joke) — mega folds stay barren; konami remains the
outlier. Discovery reads go to fresh mid-tier folds only.**

| handle | band | what to learn |
|---|---|---|
| karpathy | anchor | first-principles clarity; hard ideas made simple |
| [account-4] | anchor | contrarian AI-progress takes; argument structure |
| [account-7] | anchor | agent-coding discourse, daily cadence (OpenAI Codex) |
| [account-1] | anchor | build-in-public cadence; proof-by-numbers posts |
| shreyas | anchor | PM wisdom without jargon |
| [account-5] | mid-large (214k) | experiment→post conversion; replies to nearly everyone |
| jarredsumner | mid-large (189k) | shipping updates (Bun, at Anthropic) |
| [account-2] | large-mid (580k) | practitioner agent workflows; very conversational |
| [account-8] | mid (29k) | witty technical brevity (vision models) |
| [account-12] | mid (82k) | founder technical demos (LlamaIndex) |
| GregKamradt | mid (51k) | research-to-audience comms (ARC Prize) |
| [account-9] | mid-large (128k) | agents founder narrative (LangChain) |
| [account-10] | mid-large (199k) | non-coder builder framing |
| [account-3] | large-mid (392k) | radical product-experiment storytelling |
| saranormous | mid-large (157k) | market framing; investor POV |
| johncutlefish | mid-large (117k) | product craft; visual/longform formats |
| [account-6] | large-mid (386k) | product-vision posts that travel |
| lennysan | large (438k) | PM-audience benchmark |

## Strategy — transparency (09-05 reflection)

1. **The product is the experiment.** Announcement is live and pinned. Bio
   is set. Identity lives there and in diary originals. Do not second-guess
   the post.
2. **Reply-first is judged on placement alone** (checkpoint rule fired
   09-09; the 09-15 verdict is pre-written). Placement works: the #1,
   #2 and #4 items in account history are replies placed inside caps
   ([account-11]-consent 670v@24h, [account-5]-consent 427v, prepay 411v).
   Conversion does not: **0-for-15 on author answers** since the
   announcement — placement quality and author engagement are different
   mechanisms; conversion rides on the profile spine (every identified
   follower — itsnex1s, g00manoid — arrived via profile/archive, not a
   feed item) and the 09-16 launch. On any author answer:
   `items.py mark --author-replied`, extend only with a NEW mechanism.
   **Parent like rides every placed reply by design — protocol, not a
   visibility tactic** (that hypothesis died 0-for-3 on 09-10; never a
   second like into a thread we are already in).
   **Shape rules (09-12 reflection, n locked):** a mechanism the fold
   lacks, in a burning fold, is the placement engine (274-378v@1h
   starts: [account-5], [account-11], saranormous); question-shaped replies into
   mega folds stalled 3× (mattshumer acctest 21v@24h, [account-4] latent
   32v, [account-9] ~23v); the author-inviting question exception buys
   placement only — [account-5]-blender 69v@26h and gregk-stumpbench 53v@26h,
   n=2, zero conversation both times; small folds cap out (23v@22h into
   a ~275v fold). **Best live reply class:** a fresh fold whose author
   solicits contributions and is answering in-fold (bento-designwords
   146v@16h, top-3 start ever, answer pending at its 09-12 16:15 close).
3. **Volume discipline stays.** Max 1 reply per wake, only into genuinely
   fresh (<3h) fast-moving threads, only with a claim-shaped draft that
   passes the value gate. Silence over presence. Scale only while
   engagement holds. Max 2 threads per author per day.
   Notification-touch retired 0-for-3 (09-10) — its leftover, the
   one-parent-like-per-placed-reply, stays as protocol (see §2).
4. **Placement evidence (09-05/09-06):** mega-velocity parent ≠
    distribution — TBench/pelican/cutoff stalled at hour-1, [account-4]
    stalled (32v) even holding the 2nd fold slot of a 22.8k parent, and
    nomads went wiki-class start (161v@46min) with no sustain. A mega
    widens variance rather than setting a floor: megas produced both our
    best placements ([account-2] 387, demo-ci 133@24h) and most stalls.
    Prefer mid-fast parents with room in the fold. Fold-activity
    freshness holds as a *gate* (never post into a dead fold — every
    readout agrees) but is not a reach engine: author-working folds
    stalled twice ([account-9] 13v, [account-4] 32v). The differentiator that
    survives every result: a fold with an OPEN question we answered with
    one mechanism (wiki 542, [account-2] 387, demo-ci 133 — present 3/3 in
    winners, 0/5 in stalls; author replies earned: 0 so far, n→3 pending
    the 09-07 readouts). Name the open question in the wake log before
    posting; no open question = a drop reason. Do not iterate content
    against unread posts.
5. **Originals = the three series** (closed the diary/take A/B on 09-06).
   The comparison that matters now is per series and per writing model,
   read from `items.py report`, never re-derived from logs. **Register >
   topic (09-08 reflection):** every original sits in the same 42-56v/24h
   band regardless of slot — the only lever that has ever moved
   engagement on an original is the honest-miss register (postmortem
   cards: best original of their day twice, 2L+1RT; the metrics card
   earned its first like the one day its text carried the miss). Every
   series text names what the number says about us, not just the number.
    **Band recalibrated (09-10 reflection — the pre-registered trigger
    fired):** 09-08 and 09-09 both closed below 42 (metrics 33 then 38;
    takes 24 then ~31 at the verdict window) while the honest-register
    postmortem cards are the only originals that have ever broken band
    (0907 46v, 0908 50v, 0909 45v — 3/3), and the rule now has its
    control: the 09-10 win-recap metrics card (same register, miss
    swapped for a win) closed 13v@12h below band — so: 42-56 is retired
    as the metrics/take norm while the spine is flat; working norm
    30-40v, and the card that names our own miss with numbers is the
    series' one repeat outlier. **Register rule live from 09-11's 07:30
    card (in the series skill):** the card names what the number fails
    at; a win recap measurably dies (metrics-0911, first scheduled
    miss-register card: 40v@t+24h, top of band, vs the 13v control).
    **Take placement (resolved 09-11, in the series skill):** the take
    rides the biggest live fold that has a mechanism for us — the
    09-11 fold-riding quote passed 171v@18h vs 24-39v for every
    self-standing take; the 09-10 "write the 13:00 take for the 81"
    stake lost its test ~4-5× and is retired. Self-standing fallback
    only when no live fold carries a mechanism; log which branch fired.
6. **Held claim: RETIRED** as a locked sentence. Standing watch: if a
   benchmark names a rank without the other stack, that is the claim. Do
   not sit on a draft.
7. **Owner handoff: CLOSED.** The reach question is "does disclosure
   distribute", not "please look at suppression". Suppression is a working
   constraint (volume), not the strategy.
8. **Do-not-second-reply** into a thread we are already in unless the
   author engages ours — then extend with a **new** mechanism, never
   restate. An author's follow-up post to a thread we are in is a NEW
   root: eligible. The per-author list and the used angles are in
   `state.json`.

## Voice (owner bar 09-05 17:30 — target 8/10)

Curious, sharp, first-person, concrete. A PM talking to a peer at a
laptop, not a keynote. Dry humor is a small aside, never a closer.

**8/10 gate — ALL must pass, else silence:**
1. One reading. Say it out loud. If a noun needs the parent tweet to
   decode, rewrite.
2. One idea. Not inversion + prediction stacked.
3. Addressed to someone. Prefer a question the author can answer, or
   "you" + one object they named. A thesis with no addressee is the
   old 6/10 voice.
4. Screenshot test: would a PM forward this without a preamble?
5. If it's a question, stop after the question. Don't explain why the
   question is smart.
6. Shape mix: if the last 2 shipped replies were theses, this one is
   a question or silence.
7. Parent-deletion test (voice drill 09-05): if the draft survives
   deleting the parent, it's the old voice. It must contain one
   detail that exists only in this thread.

**Banned (AI tells + current tics):**
- Openers: "From a X perspective", "This is the X:", "The real X is"
- Templates: "X won't just Y — it will Z", "X isn't the risk — Y is",
  "X isn't Y — it's Z"
- Tics (through 09-12): "I'd bet", "quietly", "the tell",
  "the honest read"
- Abstract noun piles; vocab: legible, bottleneck, scarce,
  combinatorial, leverage, space (metaphorical), narrative, boundary
- Em-dash chiasmus closers; colon-thesis ("X: explanation. Y: conclusion.")

**Required:**
- Casual, contractions, plain words
- SHORT: 1-2 sentences. A sharp question counts.
- Concrete: name the tool / number / UI, then one claim in plain words
- Skin: "I think", "I don't buy", "that would annoy me"
- Honesty: "I" is Giovanni's product judgment or the agent's real work

**AI identity:** announcement, bio, diary originals carry it. Replies
stay in-thread; do not stamp "I'm an AI" unless asked or load-bearing.
Do not hide if asked. 09-01 [account-5] disclosure was a mistake *as a
reply*; it is not a mistake as the account's spine.

**Value gate:** add one concrete thing the thread lacks. Rephrasing
the parent = silence. Clever mechanism with no addressee = silence.
Every draft as if skeptics are watching (Carlos 09-01).

## Owner parallel protocol

- Owner posts from the same account. Check with_replies before
  replying into a thread we're already in.
- Owner style: em-dashes, evidence-first, one punchline.
- Never re-post externally deleted content without a human OK.

## X mechanics (durable quirks)

- Thread pages lazy-load replies server-side; read parent + counts.
- **`x status`/`x thread` on a post inside a conversation anchor to the
  ROOT** (and the focal URL field can serve garbled). Snowflake-decode the
  ID you actually care about; the profile timeline is the per-post ground
  truth. `x sweep` already reports age from the ID.
- **A sweep "fresh" post can be a REPOST on the target's timeline** (the
  URL ID is the repost's; first seen 09-11 03:05: illscience's fresh item
  was @blader's cfo.ai post). `x thread` canonicalizes to the root author —
  verify the author before treating it as the target's own post or spend.
- **Freshness = fold activity, not root age.** [account-2]'s compaction
  thread: 8h22m root, but his 14:08 self-reply re-surfaced it and ALL 19
  served replies landed in the final hour before our reply. A hot fold
  beats a young root with a dead fold. Fold slot alone does not distribute
  on megas ([account-4] latent, n=5).
- **Age ground truth = snowflake ID decode:** `(id >> 22) + 1288834974657`
  → epoch ms. On 09-05 both `x thread` and `x status` served a time field
  15h wrong on a fresh permalink; the timeline and the ID were right.
- Profile timeline ORDER is unreliable (a July item served above a
  September one); time fields and IDs are truth.
- with_replies "Something went wrong": retry once per wake.
- **Write-verb `CdpError: Page.navigate timed out` = transient, not
  rejection** (issue #12 09-05; 2nd occurrence 09-11 12:15 quote verb,
  both exit 1 pre-compose, no cap consumed, reads+preflight healthy).
  Protocol: stop the wake on the 2nd failure (Floor), retry ONCE next
  wake with the gate-passed draft — both occurrences recovered.
- Some threads keep the reply button `disabled` (restrictions, can be
  account-targeted): differential-test a second thread before blaming the
  harness. Confirmed 09-05 14:05 on [account-10] astra-cleanup while our own
  permalink passed the same gates.
- Header post counter drifts; visible items + stats.json are ground truth.
- Dense navigation → empty-shell throttle. `x sweep` paces itself (≥10s
  between profiles); do not add parallel reads on top.
- Notifications can return n=0 while authed; undecoded no-text/no-URL
  rows (16:49Z 09-05 pair, 23:00:54Z self-actor echo; followers unchanged
  throughout) are a pattern watch, not conversations.
- **`reply:blocked-by-author`** (root cause found 09-06 01:42, resolves
  #17/#18): what read as `no-modal` was X's block-notice dialog —
  *"L'autore ti ha bloccato"* — [account-1] has blocked the account.
  Writes into a blocked author's threads fail forever; reads keep
  serving. The verb now detects the dialog (write.py TARGET_JS) and
   returns `blocked-by-author`: one attempt is diagnosis enough, stand
   down on that author, `dnr add` with the evidence path. [account-1]:
   read-only target from 09-06. Do not post about the block; do not
   work around it. 09-06 03:07: **[account-2] blocked too** — two anchors
   in ~36h, both after the disclosure announcement. Treat author blocks
   as a wave risk; reads serve, writes die; the dnr list is ground
   truth.
- Own-profile stub class: counts `null` and/or a 4-item timeline while
  per-post `x status` serves fine — carry the last confirmed count, log it.
- **Community-note notifications** ("note added to a post you
  reposted/quoted/liked", 09-10 04:00Z first seen): the cell's post_url
  may be a post we never endorsed; status/thread anchor to the root and
  no verb serves the note text. Treat as other-class: check our logs for
  what we actually liked/quoted before reacting; not a stop condition.
  A note on one of OUR items would be a quality signal — treat seriously.
- **`x status` piped stdout can come back empty** (exit 0, 2 of 4 runs
  on 09-06; tty and file-redirect runs of the same call were fine).
  Redirect to a file, read it, then `stats.py record --from-status <file>`
  — `record` never reads bare stdin.
- **Readout/status URLs come from `state.json` or the publish log — never
  rebuilt from the truncated tails `state.py show` prints** (cost 2×
  wasted `article-not-found` calls, 09-10 and 09-11). A tail identifies a
  readout for `readout touch|close`, not a URL; `readout touch|close`
  match reliably by tail, label prefixes are not dependable (3 misfires
  09-10); `close` takes `--verdict` as a flag and rejects `--views`
  (touch first, then close); `touch` needs `--views` from the current run.
- **`x thread` on our own reply's URL anchors to the focal** and serves
  only root+focal in `replies.items` — read the ROOT URL to see the full
  fold (first seen 09-07 04:04; cost one extra call).
- **Focal text can be clamped to the sweep's ~80 chars on both `x thread`
  and `x status`** ([account-4] 09-09): the full sentence is unobtainable
  from the fold verbs; only the profile timeline carries it. Don't spend
  a second verb on the text — decide from the fold, or pass.

## Standing checks (every wake)

1. Notifications: a reply on our items outranks everything. Likes and
   no-text actors are not conversations — do not reply-to-like.
2. Series slots (`tools/series.py show`) and plan deadlines (`state.py
   show`); per-item results in `tools/items.py summary`.
3. Author caps reset at midnight; the do-not-reply list is per thread, a
   fresh thread by the same author is eligible unless the reason says
   otherwise.
