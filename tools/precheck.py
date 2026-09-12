#!/usr/bin/env python3
"""precheck.py — decide, without an LLM, whether a wake has anything to do.

    precheck.py [--since 180] [--pace 10] [--max-silence-min 180] [--horizon-min 65]
    exit 0  -> launch the agent      exit 10 -> nothing new: skip this wake

Two thirds of wakes on 09-05 ended in "legitimate zero" after ~1.2M tokens
and ~17 minutes each. The signals they checked are all deterministic:
notifications since the last LLM wake, fresh posts by the targets since the
last LLM wake, deadlines (readouts, A/B slots) inside the next hour. This
runs those reads through the `x` CLI and launches the agent only on a
signal. Fresh posts by authors who blocked the account (do-not-reply reason
"BLOCKED BY AUTHOR …") and notifications of kind `like` are not signals on
their own. Every failure launches (fail-open): a wedged verb must never
silence the agent. A wake is also forced after --max-silence-min so caps
and memory never drift for long. The envelopes are saved to
logs/precheck-latest.json so a launched wake reuses them instead of
re-reading X.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
XCLI = ROOT / "tools" / "xcli" / "x"
MARKER = ROOT / "logs" / ".last_llm_wake"
STATE = ROOT / "memory" / "state.json"
LATEST = ROOT / "logs" / "precheck-latest.json"
SKIP = 10
# Launch mode (tools/launch_mode.sh): wakes every 15 min. A full 18-20 target
# sweep at 10 s/profile is 3-4 min on its own and the 12:02 09-06 wake took
# 13 min end to end, so a 15-min timer would find the lock held every other
# tick. Notifications are the signal that matters in those 48h; the sweep
# shrinks to a few targets at a faster pace.
LAUNCH_SWEEP_MAX, LAUNCH_PACE = 6, 5.0


def _parse(s: str, now: datetime) -> datetime | None:
    try:
        dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=now.tzinfo)


def decide(now: datetime, last_llm: datetime | None, state: dict,
           notif: dict | None, sweep: dict | None, *,
           max_silence_min: int = 180, horizon_min: int = 65,
           series_due: list[str] | None = None) -> tuple[bool, list[str]]:
    """Pure: (launch?, reasons). `None` for an envelope means the verb failed."""
    reasons: list[str] = []
    if last_llm is None:
        return True, ["no-marker"]
    silence = (now - last_llm).total_seconds() / 60
    if silence >= max_silence_min:
        reasons.append("silence:%dmin" % silence)
    for name in series_due or []:
        reasons.append("series:%s" % name)  # a fixed slot (tools/series.py) is a hard signal
    horizon = now + timedelta(minutes=horizon_min)
    for x in state.get("deadlines") or []:
        at = _parse(str(x.get("at")), now)
        if at and at <= horizon:
            reasons.append("deadline:%s" % x.get("label"))
    for r in state.get("readouts") or []:
        if r.get("status", "open") != "open" or not r.get("due"):
            continue
        due = _parse(str(r["due"]), now)
        if due and due <= horizon:
            reasons.append("readout-due:%s" % str(r.get("url", ""))[-8:])
    if not state.get("targets"):
        reasons.append("no-targets")
    if notif is None:
        reasons.append("notifications-failed")
    else:
        for row in notif.get("items") or []:
            t = _parse(str(row.get("time")), now)
            if t and t > last_llm:
                # A like is engagement to record, not a conversation to join
                # (09-06 09:07: a whole wake spent proving a like was a like).
                # It is labelled, and it launches only alongside a hard signal.
                tag = "like" if row.get("kind") == "like" else "notification"
                reasons.append("%s:%s" % (tag, ",".join(row.get("actors") or ["?"])))
    if sweep is None:
        reasons.append("sweep-failed")
    else:
        handles = sweep.get("handles") or []
        if not handles and sweep.get("errors"):
            reasons.append("sweep-empty")
        blocked = blocked_authors(state)
        for h in handles:
            if h.get("handle") in blocked:
                continue  # writes into their threads die forever; a fresh post is no signal
            for f in h.get("fresh") or []:
                created = now - timedelta(minutes=int(f.get("age_min", 0)))
                if created > last_llm:
                    reasons.append("fresh:%s@%dmin" % (h.get("handle"), f.get("age_min", 0)))
    hard = [r for r in reasons if not r.startswith("like:")]
    return (bool(hard), reasons or ["quiet"])


def blocked_authors(state: dict) -> set[str]:
    """Handles whose do-not-reply reason records an author block. The 07:01
    09-06 wake was launched for `fresh:[account-2]` four hours after [account-2]
    blocked the account — 1.5 min of CPU and a full LLM session to say
    'read-only'."""
    dnr = state.get("do_not_reply") or {}
    return {h for h, v in dnr.items()
            if str((v or {}).get("reason", "")).upper().startswith("BLOCKED BY AUTHOR")}


def run_verb(args: list[str], timeout: float) -> dict | None:
    """Run one `x` verb; its evidence dict, or None on any failure."""
    try:
        p = subprocess.run([str(XCLI), *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        print("[precheck] %s failed: %s" % (args[0], e), file=sys.stderr)
        return None
    if p.stderr:
        sys.stderr.write(p.stderr)
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout.strip().splitlines()[-1]).get("evidence")
    except (json.JSONDecodeError, IndexError, AttributeError):
        return None


def rotate(targets: list[str], offset_file: Path, limit: int) -> list[str]:
    """With 30-50 targets a full sweep is 5-8 minutes of navigation every
    hour; sweep `limit` of them per wake, round-robin, the offset persisted
    next to the other machine-local wake state."""
    if len(targets) <= limit:
        return list(targets)
    try:
        off = int(offset_file.read_text().strip() or 0) % len(targets)
    except (OSError, ValueError):
        off = 0
    picked = (targets + targets)[off:off + limit]
    try:
        offset_file.write_text(str((off + limit) % len(targets)))
    except OSError:
        pass
    return picked


def series_due_now(now: datetime, series_file: Path, items_file: Path, horizon_min: int) -> list[str]:
    """tools/series.py decides; a failure here is no series, never a crash."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import series as series_mod  # noqa: WPS433
        if not series_file.exists():
            return []
        d = series_mod.load(series_file)
        items = json.loads(items_file.read_text()) if items_file.exists() else {}
        return series_mod.due(d, items, now, horizon_min)
    except Exception as e:  # noqa: BLE001
        print("[precheck] series check failed: %s" % e, file=sys.stderr)
        return []


def main(argv: list[str] | None = None, *, runner=run_verb, now: datetime | None = None,
         marker: Path = MARKER, state_file: Path = STATE, latest: Path = LATEST,
         series_file: Path = ROOT / "memory" / "series.json",
         items_file: Path = ROOT / "memory" / "items.json") -> int:
    ap = argparse.ArgumentParser(prog="precheck.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--since", type=int, default=180, help="sweep freshness window, minutes")
    ap.add_argument("--pace", type=float, default=10.0, help="seconds between profile navigations")
    ap.add_argument("--max-silence-min", type=int, default=180)
    ap.add_argument("--horizon-min", type=int, default=65)
    ap.add_argument("--sweep-max", type=int, default=20, help="targets swept per wake (round-robin)")
    a = ap.parse_args(argv)
    now = now or datetime.now().astimezone()
    last_llm = _parse(marker.read_text(), now) if marker.exists() else None
    try:
        state = json.loads(state_file.read_text()) if state_file.exists() else {}
    except json.JSONDecodeError:
        state = {}
    launch_mode = bool(state.get("launch_mode"))
    sweep_max = min(a.sweep_max, LAUNCH_SWEEP_MAX) if launch_mode else a.sweep_max
    pace = min(a.pace, LAUNCH_PACE) if launch_mode else a.pace
    targets = rotate(state.get("targets") or [], latest.parent / ".sweep_offset", sweep_max)
    notif = runner(["notifications", "--limit", "20"], 180)
    sweep = runner(["sweep", *targets, "--since", str(a.since), "--pace", str(pace)], 900) if targets else None
    series_due = series_due_now(now, series_file, items_file, a.horizon_min)
    launch, reasons = decide(now, last_llm, state, notif, sweep,
                             max_silence_min=a.max_silence_min, horizon_min=a.horizon_min,
                             series_due=series_due)
    record = {"t": now.isoformat(timespec="minutes"), "last_llm": last_llm.isoformat(timespec="minutes") if last_llm else None,
              "launch": launch, "reasons": reasons, "series_due": series_due, "swept": targets,
              "launch_mode": launch_mode,
              "notifications": notif, "sweep": sweep}
    try:
        latest.parent.mkdir(parents=True, exist_ok=True)
        latest.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n")
    except OSError as e:
        print("[precheck] could not write %s: %s" % (latest, e), file=sys.stderr)
    print("[precheck] %s — %s" % ("LAUNCH" if launch else "SKIP", ", ".join(reasons[:8])), file=sys.stderr)
    print(json.dumps({"launch": launch, "reasons": reasons}))
    return 0 if launch else SKIP


if __name__ == "__main__":
    sys.exit(main())
