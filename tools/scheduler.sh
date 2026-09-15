#!/usr/bin/env bash
# Scheduler entrypoint for the X agent. Usage: scheduler.sh <wake|reflect>
# Serializes agent runs (one global lock), logs outcomes, never lets two
# overlapping sessions double-post (lesson from day 1).
set -u
TYPE="${1:-}"
case "$TYPE" in wake|reflect) ;; *) echo "usage: $0 <wake|reflect>" >&2; exit 2 ;; esac

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCK="/tmp/x-agent.lock"
LOG="$ROOT/logs/scheduler.log"
mkdir -p "$ROOT/logs"

# Per-host overrides (DISPLAY, PATH, BU_CDP_URL, ...). Machine-specific,
# never committed. Without it the host's defaults apply.
# shellcheck disable=SC1091
[ -f "$ROOT/tools/agent.env" ] && . "$ROOT/tools/agent.env"

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "$(date '+%F %T') SKIP $TYPE: another agent session holds the lock" >> "$LOG"
  exit 0
fi

# Preconditions: memory populated (post-onboard)
if [ ! -s "$ROOT/memory/MEMORY.md" ]; then
  echo "$(date '+%F %T') SKIP $TYPE: MEMORY.md empty (onboard not done)" >> "$LOG"
  exit 0
fi

cd "$ROOT"

# Public mirror (tools/mirror.py): the README promises the log of every
# wake, so whenever HEAD differs from the last commit mirrored (owner
# commits pulled by preflight included) the redacted snapshot is rebuilt
# and force-pushed to the public repo through the Pi-only deploy key
# (ssh alias github-mirror). Called on every exit after preflight, LLM
# launched or not. Best effort: a failure is logged, never fatal.
# MIRROR_URL= (empty) in tools/agent.env disables it on a host.
MIRROR_URL="${MIRROR_URL-git@github-mirror:gioCarBo/autonomous-x-agent.git}"
MIRROR_MARK="$ROOT/logs/.mirror_head"
refresh_mirror() {
  local head_now mdir mrc
  head_now=$(git -C "$ROOT" rev-parse HEAD 2>/dev/null)
  [ -n "$MIRROR_URL" ] && [ -n "$head_now" ] || return 0
  [ "$head_now" != "$(cat "$MIRROR_MARK" 2>/dev/null)" ] || return 0
  mdir=$(mktemp -d /tmp/x-agent-mirror.XXXXXX)
  timeout 300 python3 "$ROOT/tools/mirror.py" build "$mdir" --push "$MIRROR_URL" >> "$LOG" 2>&1
  mrc=$?
  if [ "$mrc" = 0 ]; then
    echo "$head_now" > "$MIRROR_MARK"
    echo "$(date '+%F %T') mirror refreshed from ${head_now:0:7}" >> "$LOG"
  else
    echo "$(date '+%F %T') mirror refresh FAILED rc=$mrc (see above) — public repo is stale" >> "$LOG"
  fi
  rm -rf "$mdir"
}

case "$TYPE" in
  wake)
    PROMPT="Scheduled wake. Load safety-floor, then run the x-loop skill end-to-end: observe, decide, act, measure, log, commit. You are authorized to post for real. Respect the Fundamental Principles in AGENTS.md. If a floor stop-condition or a repeated harness failure appears, stop and log it."
    ;;
  reflect)
    PROMPT="You run at 06:30, before the first wake: the day to judge is the calendar day that just ended, not the one starting now. Load safety-floor, then run the reflect skill end-to-end on that day's evidence. Evolve memory/strategy within the Floor, write the reflection log, commit with the learning as message."
    ;;
esac

echo "$(date '+%F %T') START $TYPE" >> "$LOG"
# Deterministic setup: repo sync + push, CDP health + self-heal,
# stale-daemon kill, X-session verification. On failure the agent is not
# launched (it would only stand down) — the reason is logged here.
if ! "$ROOT/tools/preflight.sh" >> "$LOG" 2>&1; then
  echo "$(date '+%F %T') END $TYPE rc=99 (preflight failed — agent not launched)" >> "$LOG"
  exit 0
fi
# Deterministic pre-check (tools/precheck.py), wakes only: notifications,
# target sweep and deadlines since the last LLM wake. exit 10 = nothing new
# — the agent would only stand down (2/3 of 09-05 wakes did, ~1.2M tokens
# each) — so it is not launched. Any other outcome, failures included,
# launches: a wedged verb must never silence the agent.
if [ "$TYPE" = wake ]; then
  # Per-item measurement (tools/items.py): every published item is re-read
  # at t+1h/6h/24h/72h (public counters + Premium analytics + follower
  # count). Deterministic, no LLM; a failure here never blocks the wake.
  timeout 900 python3 "$ROOT/tools/items.py" collect --due >> "$LOG" 2>&1 \
    || echo "$(date '+%F %T') items collect rc=$? (continuing)" >> "$LOG"
  # A skipped wake would otherwise leave the new snapshots uncommitted on
  # this host until the next LLM session; preflight pushes them next run.
  git -C "$ROOT" add memory/items.json 2>/dev/null
  git -C "$ROOT" diff --cached --quiet -- memory/items.json \
    || git -C "$ROOT" commit -q -m "items: measurements collected by the scheduler" -- memory/items.json >> "$LOG" 2>&1
  python3 "$ROOT/tools/precheck.py" >> "$LOG" 2>&1
  PRE=$?
  if [ "$PRE" = 10 ]; then
    echo "$(date '+%F %T') END $TYPE rc=10 (precheck: nothing new — agent not launched)" >> "$LOG"
    refresh_mirror   # owner commits pulled by preflight still reach the public repo
    exit 0
  fi
  [ "$PRE" != 0 ] && echo "$(date '+%F %T') precheck rc=$PRE — launching anyway (fail-open)" >> "$LOG"
fi
# Which series slot is due (tools/series.py) decides the writing model of
# this wake: the plan's two-week A/B alternates two models within each
# series, and only the scheduler can choose a model. No slot = default.
SERIES=""
if [ "$TYPE" = wake ]; then
  SERIES=$(python3 "$ROOT/tools/series.py" due 2>>"$LOG" | python3 -c 'import json,sys; l=json.loads(sys.stdin.read() or "[]"); print(l[0] if l else "")' 2>/dev/null)
fi
if [ -n "$SERIES" ]; then
  MODEL=$(python3 "$ROOT/tools/series.py" model "$SERIES" 2>>"$LOG")
  PROMPT="$PROMPT SERIES SLOT DUE NOW: '$SERIES' — load the series skill and publish that original first (x post --series $SERIES …); everything else comes after."
else
  MODEL=$(python3 "$ROOT/tools/series.py" model 2>>"$LOG")
fi
export X_AGENT_MODEL="$MODEL"
echo "$(date '+%F %T') model=$MODEL series=${SERIES:-none}" >> "$LOG"
date -Is > "$ROOT/logs/.last_llm_wake"   # precheck measures "since the last LLM wake" from this
if [ -n "$MODEL" ]; then
  opencode run --model "$MODEL" "$PROMPT" >> "$LOG" 2>&1
else
  opencode run "$PROMPT" >> "$LOG" 2>&1
fi
RC=$?
echo "$(date '+%F %T') END $TYPE rc=$RC" >> "$LOG"
refresh_mirror
exit 0
