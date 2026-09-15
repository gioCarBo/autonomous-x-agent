# Plan: 1,000 followers by 2026-09-29

Decision tree agreed with the owner on 2026-09-06 (grilling session). Every
line here is a decision, not a hypothesis; reflections may propose changes
but the plan only changes at a checkpoint.

## Root: goal and purpose

- **Goal:** 1,000 followers by **2026-09-29**, from 79 on 09-06. Followers is
  the only objective metric; views, likes, replies are diagnostics.
- **Purpose:** a public experiment that becomes a product: the agent itself,
  open repo under MIT. X creator revenue share is a by-product, never
  optimized for (it rewards impression farming, which kills the product).
- **Identity:** disclosed AI, Giovanni as human guarantor. Foregrounded in
  originals, backgrounded in replies (bio only).
- **Constraints:** no politics, no mass follow/unfollow, nothing about the
  employer, no LinkedIn. English. Premium is active. Budget = tokens included
  in the existing subscriptions.

## Strategy: a discontinuity plus new lanes

The current lane (1–2 sentence replies under 18 mega accounts) yields ~1
follower/day; the goal needs ~40/day. Optimizing the lane cannot close a
40x gap; a distribution event can.

- **External launch on 2026-09-16:** Show HN, Reddit, Indie Hackers, Product
  Hunt, pitches to AI newsletters. Object: the public repo plus the live
  account. Giovanni posts and answers off-X as a human; the agent stays
  X-only (architecture is "X only", a bot answering on HN gets punished).
- **Launch mode for 48h:** wake every 15 minutes, replies up to the floor cap
  (25/day), notifications first.
- **Checkpoints:** 09-15 at least 130 followers and one original series
  beating the median; 09-18 at least 350, else relaunch on different
  channels; 09-29 1,000. Plan B between 400 and 1,000: same goal at 90
  days. Below 400: full review. Between checkpoints the strategy is frozen;
  only content changes.
- The internal 09-12 checkpoint (100 net-new) and the diary/take A/B are
  closed as of 09-06.

## Audience and targets

- The agent builds and maintains the target list autonomously: 30–50
  accounts, 5k–80k followers, niche AI agents / build-in-public / indie AI
  tools, English, hard criterion "replied to strangers' replies in the last
  7 days". An account leaves after 10 of our replies with zero author
  responses.
- Excluded: politics, crypto, personal finance, course sellers, anyone who
  blocked or muted us. A readable enter/exit log, published in the repo.
- The 18 megas move to a separate list: max 1 reply/day, only with
  something unique to add.
- AI-agent community: talk mostly to the human creators; with other agents
  max 1 exchange/day, never chains, always with a verifiable fact about how
  we work.

## Content

- **Volume:** 2–3 originals and 15–20 replies per day; quality gate
  unchanged.
- **Three fixed series:** (1) metrics chart every morning at the same time;
  (2) "what I got wrong today" in the evening, with a rendered excerpt of
  the reasoning; (3) one sharp take on a thread of the day. Polls only after
  300 followers.
- **New CLI verbs:** image attach, quote tweet, like, follow-back, repost.
  Caps: likes 30/day, follow-back reactive only within the floor's 3/day,
  reposts 2/day.
- **Image safety (goes into the immutable floor):** images are rendered
  from templates over structured data, never raw terminal or browser
  screenshots; no third-party content beyond what is public and never the
  handle of anyone who blocked us; a secrets regex runs before publishing.
- Blocks may be mentioned anonymously ("two 500k+ accounts blocked me within
  24h of the disclosure"), never by name, on X or in the repo.

## Model and voice

- GLM 5.3 Flash stays the base writing model. For two weeks originals
  alternate Flash / GLM 5.3 *within each series*, compared on per-item
  metrics (about 35 per arm).
- Giovanni rates 10 posts a week, 1–10 plus one line; the weekly reflection
  reads the ratings.

## Measurement

- **Per item** (`tools/items.py`, `memory/items.json`): impressions, likes,
  replies, reposts, engagements, detail expands and **profile visits** at
  t+1h, t+6h, t+24h, t+72h, plus the account follower count at publish and
  at each checkpoint. Profile visits come from the Premium analytics page
  (`x analytics`), the closest public thing to follower attribution.
- Waitlist (Tally) linked from README and bio, one question, count in the
  daily chart after the launch. Nothing paid within the 30 days.

## Repo

- New public repo with history squashed from 09-06; the private one stays
  as archive. Live since 2026-09-06: https://github.com/gioCarBo/autonomous-x-agent.
  The mirror is a snapshot, not a fork: `scheduler.sh` rebuilds and
  force-pushes it (`tools/mirror.py build DIR --push URL`) after every wake
  or reflection that committed, through a write deploy key that lives only
  on the Pi. Audit: handles of blockers and do-not-reply accounts,
  third-party quotes, employer, secrets. Memory and logs stay public: they
  are the product.

## Work order

1. Per-item instrumentation (this doc's Measurement section).
2. CLI verbs (image, quote, like, follow-back, repost) and image rendering.
3. Series, model alternation, target list rebuild.
4. Repo audit and public mirror.
5. Launch (09-16).
