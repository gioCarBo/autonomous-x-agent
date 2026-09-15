# CLI as the single X action path, hard-fail with bug issue

Every X.com interaction the agent performs — reads and writes — goes through
the `x` CLI (tools/xcli/), which drives the dedicated agent Chrome via CDP.
Raw browser-use is no longer an action path after cutover. A failed write
verb never retries and never falls back: it files a deduplicated bug issue
(error signature + screenshot + diagnostics) for the owner and reports
failure. We chose this over the previous raw-browser-use-in-every-wake
approach and over an agent-side fallback because page interaction was the
dominant failure class (composer quirks, wedged tabs, interstitials,
rendering flakes) and only tested, deterministic code fixes it; a fallback
path would reintroduce exactly the chaos the CLI exists to remove.

## Consequences

- The agent's skill shrinks to judgment (what to say, where, voice, value
  gate); mechanics live in the CLI and are testable without an LLM.
- Every write verb must return evidence (URL + re-read text) or a non-zero
  exit; "probably posted" is not a state.
- Owner is in the loop for CLI bugs by design: agent downtime on a broken
  verb is intentional until the issue is fixed.
