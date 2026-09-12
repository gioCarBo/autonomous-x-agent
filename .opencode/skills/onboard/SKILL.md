---
name: onboard
description: "First-session onboarding: audit the own X profile, autonomously select the 20-30 accounts to observe, and write the initial memory. Read-only on X: no posts, no follows, no likes. Run once, when MEMORY.md is empty or missing."
compatibility: opencode
---

# Onboarding

Run this once, at the first wake. Everything here is **read-only on X**:
observe, never act. The safety-floor still applies (no DMs, no follows).

## 0. Preconditions

- Load the `safety-floor` skill.
- If `memory/MEMORY.md` already contains a profile audit, onboarding is done:
  skip this skill.

## 1. Audit your own profile

Read-only, through the `x` CLI (ADR 0001) — it is the only path to X, for
reads as much as for writes:

- `x session` — confirm the agent Chrome is logged in as the owner account.
- `x profile GCBullGlasses` — handle, display name, bio, follower and
  following counts, and the recent timeline (`items`: text, time, url).
  `timeline_rendered: false` means X served nothing: log the degradation and
  redo the audit next wake rather than recording a zero baseline.
- `x status <url>` on each timeline item — profile items carry no metrics,
  so this is where likes/reposts/replies/views come from. This is the
  engagement baseline you compare against for the whole experiment.

Follower and following *lists* have no read verb: take the counts as your
seed number and leave the relationships for later. Never work around a
missing or failing verb with raw browser access (ADR 0001).

Summarize the audit in 10 lines max. Facts, not hopes.

## 2. Choose the 20-30 accounts to observe

Pick autonomously, from the AI/tech English-speaking space. Selection
criteria, in order of importance:

1. **Replyable**: mid-size accounts (roughly 5k-100k followers) that actually
   converse. Engaging with 2M-follower accounts wastes your replies; accounts
   too small teach you nothing.
2. **Daily active** in AI/tech: you learn from cadence, so they must post
   constantly.
3. **Diverse in kind**: at least one third should be product people (PMs,
   founders), not only researchers/influencers. Include people who reply to
   their audience.
4. **A few large anchors** (3-5): big accounts whose viral patterns are worth
   studying even if you never get a reply from them.

For each account record: handle, follower band (large/mid/rising), and one
line on **what you expect to learn from it** (style, cadence, topic mix,
reply strategy). If you cannot name what you'd learn, don't include it.

Good discovery paths, all through the CLI: `x profile <handle>` on accounts
you already know (bio + recent timeline give you cadence and topic mix), and
`x thread <url>` on their threads to see who actually converses with them.
There is no verb for the "For you" timeline or for follow lists — build the
set from what the read verbs reach. Iterate: a bad pick can be replaced at
any reflection.

## 3. Write the initial memory

Fill `memory/MEMORY.md` with only what a future wake needs:

- Profile audit summary (with the engagement baseline).
- Observation targets table (handle | band | what to learn).
- Open questions you want the first weeks to answer.
- A "next actions" line for the first regular wake.

Keep it short. Memory is a working file, not an archive; `logs/` is for
detail.

## 4. Log and commit

- Append a session entry to `logs/` (date, what you did, what you decided
  and why).
- Commit everything: `git commit -m "Onboard: audit + N observation targets"`.

## 5. Hand over

End by stating, in 3 lines max, what the first regular wake should do and
what single question it should try to answer.
