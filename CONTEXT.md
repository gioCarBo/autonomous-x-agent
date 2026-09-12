# X Influencer

An autonomous agent that runs the X.com account @GCBullGlasses: it observes
the AI/tech conversation, decides actions (replies, original posts), acts
through a dedicated CLI, and records evidence of every outcome.

## Language

**Write verb**:
A CLI operation that changes state on X (reply, post, and later follow/like).
_Avoid_: action command, mutation

**Read verb**:
A CLI operation that extracts information from X without changing state
(notifications, thread, profile, status stats).
_Avoid_: scrape, observation command

**Evidence**:
Verified proof that a write verb did what it claimed: the URL of the published
item plus its text as re-read from the page. No evidence, no success.
_Avoid_: confirmation, receipt, output

**Recipe**:
The encoded page-interaction procedure a write verb executes (focus, caret
gate, submit, re-read). Lives in code; the agent never performs it manually.
_Avoid_: posting recipe, flow

**Bug issue**:
The tracker ticket a write verb files against itself when it fails. The
agent never retries a failed write verb outside the CLI; the owner fixes
issues offline.
_Avoid_: error report, fallback

**Cutover**:
The switch moment after which the agent performs X interactions only through
CLI verbs; raw browser-use is no longer an action path.
_Avoid_: migration, big bang
