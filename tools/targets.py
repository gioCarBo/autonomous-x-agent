#!/usr/bin/env python3
"""targets.py — the observation list, built and pruned by rule, not by taste.

    targets.py show
    targets.py evaluate HANDLE            read X (x profile + x replies), print the verdict
    targets.py add HANDLE --why TEXT      evaluate; add only if eligible; log
    targets.py drop HANDLE --why TEXT     remove; log
    targets.py review                     auto-drop: >=10 of our replies, 0 author answers
    targets.py mega add|drop HANDLE       the separate mega list (max 1 reply/day, unique angle only)

Plan 2026-09-06 (Q9/Q17/Q27): 30-50 accounts, 5k-80k followers, that
actually answer strangers (>= 5 replies to >= 3 other accounts in the last
7 days), no politics / crypto / personal finance / course sellers, nobody
who blocked or muted us. An account leaves after 10 of our replies with
zero answers from its author. The agent proposes candidates (authors who
answered in threads it read, quote-tweeters, people who answered us); this
tool decides, and every entry and exit lands in memory/targets-log.md.
The 18 mega accounts of the first week live in `megas`, swept by the LLM
when it wants, never by precheck.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "memory" / "state.json"
ITEMS = ROOT / "memory" / "items.json"
LOG = ROOT / "memory" / "targets-log.md"
XCLI = ROOT / "tools" / "xcli" / "x"

MIN_FOLLOWERS, MAX_FOLLOWERS = 5_000, 80_000
MIN_REPLIES_7D, MIN_DISTINCT_7D = 5, 3
DROP_AFTER_OUR_REPLIES = 10
LIST_MIN, LIST_MAX = 30, 50

EXCLUDE = re.compile(
    r"\b(politic|election|senat|congress|maga|democrat|republican|liberal|conservative|"
    r"crypto|bitcoin|btc|eth|solana|web3|nft|token|defi|airdrop|memecoin|"
    r"forex|day ?trad|stocks?|options trad|passive income|make money|financial freedom|"
    r"course|masterclass|coaching|coach|mentorship|cohort|bootcamp|"
    r"onlyfans|nsfw|adult)\b", re.I)


def _now() -> datetime:
    return datetime.now().astimezone()


def load_state() -> dict:
    d = json.loads(STATE.read_text()) if STATE.exists() else {}
    d.setdefault("targets", []); d.setdefault("megas", []); d.setdefault("target_meta", {})
    return d


def save_state(d: dict, now: datetime) -> None:
    d["updated"] = now.isoformat(timespec="minutes")
    STATE.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n")


def log_line(text: str, now: datetime, path: Path = LOG) -> None:
    if not path.exists():
        path.write_text("# Target list changes\n\nOne line per entry or exit, written by tools/targets.py. "
                        "Criteria in the tool's docstring.\n\n")
    with path.open("a") as f:
        f.write("- %s %s\n" % (now.strftime("%Y-%m-%d %H:%M"), text))


def _count(s) -> int | None:
    if s is None:
        return None
    if isinstance(s, int):
        return s
    s = str(s).strip().replace(" ", "").replace(" ", "")
    mult = 1
    if s and s[-1] in "KkMm":
        mult = 1000 if s[-1] in "Kk" else 1000000
        s = s[:-1]
    s = s.replace(",", ".") if mult > 1 else s.replace(".", "").replace(",", "")
    try:
        return int(float(s) * mult)
    except ValueError:
        return None


def run_verb(args: list[str], timeout: float) -> dict | None:
    try:
        p = subprocess.run([str(XCLI), *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        print("[targets] %s failed: %s" % (args[0], e), file=sys.stderr)
        return None
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout.strip().splitlines()[-1]).get("evidence")
    except (json.JSONDecodeError, IndexError, AttributeError):
        return None


def verdict(handle: str, profile: dict | None, activity: dict | None, state: dict) -> dict:
    """Pure: eligibility and every reason against."""
    reasons = []
    h = handle.lower()
    dnr = {k.lower(): v for k, v in (state.get("do_not_reply") or {}).items()}
    if h in dnr and re.match(r"blocked by author|muted", str(dnr[h].get("reason", "")), re.I):
        reasons.append("blocked or muted us")
    followers = _count(((profile or {}).get("counts") or {}).get("followers")) if profile else None
    if followers is None:
        reasons.append("follower count unreadable")
    elif not MIN_FOLLOWERS <= followers <= MAX_FOLLOWERS:
        reasons.append("followers %d outside %d-%d" % (followers, MIN_FOLLOWERS, MAX_FOLLOWERS))
    bio = (profile or {}).get("bio") or ""
    m = EXCLUDE.search(bio)
    if m:
        reasons.append("bio matches exclusion (%s)" % m.group(0))
    rep, dist = None, None
    if activity is None:
        reasons.append("reply activity unreadable")
    else:
        rep, dist = activity.get("replies_to_others", 0), activity.get("distinct_accounts", 0)
        if rep < MIN_REPLIES_7D or dist < MIN_DISTINCT_7D:
            reasons.append("answers strangers too little: %d replies to %d accounts in 7d (need %d/%d)" % (
                rep, dist, MIN_REPLIES_7D, MIN_DISTINCT_7D))
    if h in {x.lower() for x in state.get("megas", [])}:
        reasons.append("already on the mega list")
    return {"handle": handle, "eligible": not reasons, "reasons": reasons, "followers": followers,
            "replies_7d": rep, "distinct_7d": dist, "bio": bio[:160]}


def evaluate(handle: str, state: dict, runner=run_verb) -> dict:
    prof = runner(["profile", handle], 120)
    act = runner(["replies", handle], 150)
    return verdict(handle, prof, act, state)


def our_record(handle: str, items: dict) -> tuple[int, int]:
    """(our replies into this author's threads, how many the author answered)."""
    h = handle.lower()
    ours = [it for it in items.get("items", []) if it.get("kind") == "reply" and (it.get("parent_handle") or "").lower() == h]
    return len(ours), len([it for it in ours if it.get("author_replied")])


def review(state: dict, items: dict, now: datetime, log=log_line) -> list[str]:
    """Drop what the rule says to drop; return the report lines."""
    out, dropped = [], []
    for h in list(state["targets"]):
        n, answered = our_record(h, items)
        meta = state["target_meta"].setdefault(h, {})
        meta.update({"our_replies": n, "author_replies": answered})
        flag = ""
        if n >= DROP_AFTER_OUR_REPLIES and answered == 0:
            dropped.append(h)
            flag = "  DROP"
        out.append("%-16s ours %2d  answered %2d  followers %s%s" % (h, n, answered, meta.get("followers", "?"), flag))
    for h in dropped:
        state["targets"].remove(h)
        state["target_meta"][h]["dropped"] = now.isoformat(timespec="minutes")
        log("- @%s: %d of our replies, 0 answers from the author (rule)" % (h, state["target_meta"][h]["our_replies"]), now)
    n = len(state["targets"])
    out.append("targets: %d (plan wants %d-%d)%s" % (n, LIST_MIN, LIST_MAX,
                                                     " — below the floor: propose candidates" if n < LIST_MIN else ""))
    return out


def show(state: dict) -> str:
    out = ["targets (%d, mid-tier, swept by precheck):" % len(state["targets"])]
    for h in state["targets"]:
        m = state["target_meta"].get(h, {})
        out.append("  %-16s %6s followers  %s replies/7d to %s  ours %s/%s answered" % (
            h, m.get("followers", "?"), m.get("replies_7d", "?"), m.get("distinct_7d", "?"),
            m.get("author_replies", 0), m.get("our_replies", 0)))
    out.append("megas (%d, max 1 reply/day, unique angle only): %s" % (len(state["megas"]), " ".join(state["megas"])))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="targets.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="verb", required=True)
    sub.add_parser("show")
    e = sub.add_parser("evaluate"); e.add_argument("handle")
    a = sub.add_parser("add"); a.add_argument("handle"); a.add_argument("--why", required=True)
    d = sub.add_parser("drop"); d.add_argument("handle"); d.add_argument("--why", required=True)
    sub.add_parser("review")
    m = sub.add_parser("mega"); m.add_argument("op", choices=("add", "drop")); m.add_argument("handle")
    args = ap.parse_args(argv)
    now = _now()
    state = load_state()
    items = json.loads(ITEMS.read_text()) if ITEMS.exists() else {}
    if args.verb == "show":
        print(show(state)); return 0
    if args.verb in ("evaluate", "add"):
        h = args.handle.lstrip("@")
        if h in state["targets"] and args.verb == "add":
            print("@%s is already a target" % h); return 0
        v = evaluate(h, state)
        print(json.dumps(v, ensure_ascii=False))
        if args.verb == "evaluate":
            return 0 if v["eligible"] else 3
        if not v["eligible"]:
            print("targets.py: not added — " + "; ".join(v["reasons"]), file=sys.stderr); return 3
        if len(state["targets"]) >= LIST_MAX:
            print("targets.py: list is full (%d); drop one first" % LIST_MAX, file=sys.stderr); return 3
        state["targets"].append(h)
        state["target_meta"][h] = {"added": now.isoformat(timespec="minutes"), "followers": v["followers"],
                                   "replies_7d": v["replies_7d"], "distinct_7d": v["distinct_7d"], "why": args.why[:200]}
        log_line("+ @%s (%s followers, %s replies/7d to %s accounts) — %s" % (
            h, v["followers"], v["replies_7d"], v["distinct_7d"], args.why[:160]), now)
        save_state(state, now); print("added @%s (%d targets)" % (h, len(state["targets"]))); return 0
    if args.verb == "drop":
        h = args.handle.lstrip("@")
        if h not in state["targets"]:
            print("targets.py: @%s is not a target" % h, file=sys.stderr); return 2
        state["targets"].remove(h)
        state["target_meta"].setdefault(h, {})["dropped"] = now.isoformat(timespec="minutes")
        log_line("- @%s — %s" % (h, args.why[:160]), now)
        save_state(state, now); print("dropped @%s (%d targets)" % (h, len(state["targets"]))); return 0
    if args.verb == "review":
        print("\n".join(review(state, items, now))); save_state(state, now); return 0
    if args.verb == "mega":
        h = args.handle.lstrip("@")
        if args.op == "add" and h not in state["megas"]:
            state["megas"].append(h); log_line("+ mega @%s" % h, now)
        elif args.op == "drop" and h in state["megas"]:
            state["megas"].remove(h); log_line("- mega @%s" % h, now)
        save_state(state, now); print("megas: %d" % len(state["megas"])); return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
