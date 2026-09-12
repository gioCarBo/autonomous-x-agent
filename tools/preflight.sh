#!/usr/bin/env bash
# Deterministic pre-flight for every agent session (wake or reflect).
# Fixes, in order, every setup failure observed so far:
#   1. CDP endpoint down/wedged  -> health check + one restart of the
#      AGENT'S OWN Chrome (chrome-agent-x.service — never the owner's)
#   2. Stale harness daemon bound to a dead endpoint -> killed, so the
#      next CLI verb reaches a live one on BU_CDP_URL
#   3+4. Wrong/dead X session -> `x session` verifies @GCBullGlasses or
#      FAIL. Tab accumulation (85 observed) needs no step any more: every
#      verb opens and closes its own tab (ADR 0001)
#   5. Stale repo (agent ran on old memory, 2026-09-01) -> git pull --rebase
#   6. Unpushed work (31 commits stranded ~21h on 09-03/04) -> git push,
#      FAIL loudly if origin is unreachable
# Idempotent; safe to re-run mid-session to self-heal.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CDP="${BU_CDP_URL:-http://127.0.0.1:9223}"
export BU_CDP_URL="$CDP"
# shellcheck disable=SC1091
[ -f "$ROOT/tools/agent.env" ] && . "$ROOT/tools/agent.env"

log()  { echo "[preflight $(date '+%H:%M:%S')] $*"; }
fail() { echo "[preflight FAIL] $*"; exit 1; }

# --- 5. repo state first: the session must read current memory -------------
if git -C "$ROOT" pull --rebase --autostash origin main >>"$ROOT/logs/preflight.log" 2>&1; then
  log "repo synced at $(git -C "$ROOT" rev-parse --short HEAD)"
else
  fail "git pull --rebase failed (see logs/preflight.log) — fix manually"
fi

# --- 6. unpushed work guard --------------------------------------------------
# A failed push must never be silent: on 09-03/04 a transient network issue
# left 31 local-only commits for ~21h while pulls kept working (anonymous
# read, authed write). Push anything pending here and FAIL loudly if it
# cannot reach origin, so the anomaly is visible in scheduler.log at once.
if [ -n "$(git -C "$ROOT" log origin/main..main)" ]; then
  N=$(git -C "$ROOT" rev-list --count origin/main..main)
  if timeout 60 git -C "$ROOT" push origin main >>"$ROOT/logs/preflight.log" 2>&1; then
    log "pushed $N pending commit(s)"
  else
    fail "git push failed after $N unpushed commit(s) (see logs/preflight.log) — work exists only on this host"
  fi
fi

# --- 1. CDP health, one self-heal restart -----------------------------------
cdp_ok() { curl -s --max-time 5 "$CDP/json/version" >/dev/null 2>&1; }
if ! cdp_ok; then
  log "CDP down — restarting chrome-agent-x (agent-owned instance)"
  systemctl --user restart chrome-agent-x.service
  sleep 8
fi
cdp_ok || { sleep 7; cdp_ok; } || fail "CDP unresponsive after restart"
log "CDP healthy on $CDP"

# --- 2. stale harness daemon -------------------------------------------------
if pgrep -f browser_harness.daemon >/dev/null 2>&1; then
  pkill -f browser_harness.daemon
  sleep 1
  log "stale harness daemon killed"
fi

# --- 3+4. X session verified via the CLI (ADR 0001) --------------------------
# `x session` opens and closes its own tab; tab hygiene is structural now.
XCLI="$ROOT/tools/xcli/x"
export XCLI_NO_ISSUE=1   # session probe is not a verb bug; preflight handles it
if OUT="$(timeout 120 "$XCLI" session 2>>"$ROOT/logs/preflight.log")"; then
  echo "$OUT" | grep -o '"handle": *"[^"]*"' | head -1
  log "X session verified as @GCBullGlasses"
  log "preflight OK"
else
  RC=$?
  echo "$OUT" >>"$ROOT/logs/preflight.log"
  if [ "$RC" = "3" ]; then
    fail "X logged out on the agent Chrome — owner login needed on the Pi screen"
  fi
  fail "x session failed rc=$RC (see logs/preflight.log)"
fi
