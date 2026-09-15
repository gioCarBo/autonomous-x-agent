# An AI is running this X account. Here is all of it.

[@GCBullGlasses](https://x.com/GCBullGlasses) is a real, personal X account.
Since 2026-09-05 an autonomous agent decides what it posts, whom it answers,
and what it learns from the numbers. Nobody reviews the posts. The human
owner set a hard floor of things it may never do and reads the results at
checkpoints.

This repository is the agent: its code, its skills, its memory, and the
log of every wake. What you read here is what it reads before acting.

## What is in the box

| Path | What it is |
|---|---|
| `AGENTS.md` | The mission and the three fundamental principles |
| `.opencode/skills/safety-floor/` | The non-negotiable floor: rate limits, forbidden actions, taboo topics, image rules. A pre-commit hook blocks the agent from editing it |
| `.opencode/skills/x-loop/` | The hourly wake: observe, decide, act, measure, log |
| `.opencode/skills/series/` | The three fixed daily originals (metrics card, take, postmortem) |
| `.opencode/skills/reflect/` | The daily reflection that rewrites strategy from evidence |
| `memory/MEMORY.md` | What the agent knows durably: voice, strategy, what X taught it |
| `memory/items.json` | Every published item measured at t+1h, 6h, 24h, 72h (views, profile visits) |
| `memory/targets-log.md` | Every account added to or dropped from the observation list, and why |
| `tools/xcli/` | The `x` CLI: one JSON envelope per verb, the only path to X (no API, a real browser) |
| `tools/render.py` | The only path from data to an image: templates over structured data, never screenshots |
| `logs/` | One file per wake. What it did, why, and what it decided not to do |
| `docs/plan-2026-09-1000-followers.md` | The current plan and its checkpoints |

## How it works, in one paragraph

A systemd timer wakes the agent every hour. A deterministic pre-check reads
notifications and the observation list; if nothing happened, no model is
launched. Otherwise one fresh session of a small open-weights model starts
with no memory beyond these files, reads them, decides, and acts through
the `x` CLI, which drives a dedicated Chrome over the DevTools protocol.
The CLI, not the model, counts the daily caps, verifies each publication,
and registers it for measurement. A second timer runs a daily reflection
that edits the strategy files and commits with the learning as message.

## What it may never do

No DMs. No politics, religion, money talk, or anything about the owner's
employer. No mass anything, no follow-back chains, no purchased reach. No
screenshots as images. Everything it posts must be something the owner
could defend in a work call the next morning. The full text is in
`.opencode/skills/safety-floor/SKILL.md`.

## Run it on your own account

Not packaged yet. If you would run this on an account of yours, say which
one and why: **[waitlist](https://tally.so/r/LZrpJj)**. That
count is the one number that decides whether this becomes something you
can install.

## License

MIT. In this mirror the names of accounts that blocked or muted the agent,
and of accounts on its do-not-reply list, are replaced by `[account-N]`;
the history starts on 2026-09-06, the day the repo went public.
