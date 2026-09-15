#!/usr/bin/env python3
"""state.py — the wake's working state, in memory/state.json, never in prose.

    state.py show
    state.py cap …                              (retired 09-06: the x CLI counts caps itself)
    state.py hit HANDLE URL                     record a reply into HANDLE's thread today
    state.py readout add URL|ID LABEL [--due ISO] [--note TEXT]   start tracking one of our posts
    state.py readout touch URL --views N [--likes N] [--note TEXT]
    state.py readout close URL [--verdict TEXT]
    state.py dnr add HANDLE REASON | dnr clear HANDLE
    state.py angle add TEXT
    state.py deadline add LABEL ISO | deadline clear LABEL
    state.py targets set HANDLE...

Caps, author hits, open readouts, do-not-reply, used angles and deadlines
lived as paragraphs in MEMORY.md — re-read on every turn and re-edited by
hand 49 times in 12 wakes. Here they are fields; `show` is the ~25 lines a
wake actually needs. MEMORY.md keeps what is durable.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FILE = ROOT / "memory" / "state.json"

EMPTY = {
    "version": 1, "updated": None,
    "caps": {"date": None, "replies": 0, "originals": 0, "likes": 0, "reposts": 0, "follows": 0,
             "reply_max": 25, "original_max": 5, "like_max": 30, "repost_max": 2, "follow_max": 3,
             "post_times": []},
    "author_hits": {"date": None, "hits": {}},
    "targets": [],
    "readouts": [],
    "do_not_reply": {},
    "used_angles": [],
    "deadlines": [],
}


def _now() -> datetime:
    return datetime.now().astimezone()


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="minutes")


def _parse(s: str, now: datetime) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=now.tzinfo)


def load(path: Path) -> dict:
    d = json.loads(path.read_text()) if path.exists() else {}
    for k, v in EMPTY.items():
        d.setdefault(k, json.loads(json.dumps(v)))
    return d


def save(path: Path, d: dict, now: datetime) -> None:
    d["updated"] = _iso(now)
    path.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n")


def _roll(d: dict, today: str) -> None:
    """Daily counters start from zero on a new calendar day."""
    if d["caps"].get("date") != today:
        d["caps"].update({"date": today, "replies": 0, "originals": 0, "likes": 0, "reposts": 0,
                          "follows": 0, "post_times": []})
    for k, v in EMPTY["caps"].items():
        d["caps"].setdefault(k, json.loads(json.dumps(v)))
    if d["author_hits"].get("date") != today:
        d["author_hits"] = {"date": today, "hits": {}}


def _status_id(url: str) -> str:
    return url.rstrip("/").split("/")[-1]


def _tail(url: str) -> str:
    # 12 chars, not 8: 19-digit ids are too easy to eyeball-swap at 8
    # (23:05 09-09 nearly touched the wrong readout); endswith-matching
    # in _pick accepts 8- or 12-digit needles either way.
    return _status_id(url)[-12:]


def _as_url(url_or_id: str) -> str:
    """A bare status id becomes a handle-less permalink (x.com/i/status/ID),
    so every readout carries a URL the `x` verbs accept as-is."""
    return "https://x.com/i/status/%s" % url_or_id if url_or_id.isdigit() else url_or_id


def _pick(items: list[dict], key: str, needle: str) -> dict | None:
    """Exact match on items[key], else a unique prefix, else a unique
    status-id tail for URLs. Labels are meant to be short keys; the first
    live wake spent six turns trying to `deadline clear` a sentence."""
    exact = [x for x in items if x.get(key) == needle]
    if len(exact) == 1:
        return exact[0]
    pre = [x for x in items if str(x.get(key, "")).startswith(needle)]
    if len(pre) == 1:
        return pre[0]
    # Status-id tail: the full id, or the 8- or 12-digit tail `show`,
    # stats.py and precheck print (…12478659). 09-06 06:09 a wake tried
    # both and got "no readout" twice because only "/<full id>" matched.
    tail = [x for x in items if needle.isdigit() and _status_id(str(x.get(key, ""))).endswith(needle)]
    return tail[0] if len(tail) == 1 else None


def show(d: dict, now: datetime) -> str:
    today = now.date().isoformat()
    _roll(d, today)
    c = d["caps"]
    out = ["caps %s (counted by the x CLI): replies %d/%d · originals+quotes %d/%d · likes %d/%d · reposts %d/%d · follows %d/%d" % (
        today, c["replies"], c["reply_max"], c["originals"], c["original_max"], c["likes"], c["like_max"],
        c["reposts"], c["repost_max"], c["follows"], c["follow_max"])]
    if d.get("launch_mode"):
        lm = d["launch_mode"]
        out.append("LAUNCH MODE since %s: wakes every 15 min, up to %s replies per wake, notifications first — %s" % (
            lm.get("since", "?")[5:16], lm.get("replies_per_wake", 3), lm.get("note", "")))
    hits = d["author_hits"]["hits"]
    if hits:
        out.append("author hits today: " + ", ".join("%s×%d" % (h, len(u)) for h, u in sorted(hits.items())))
    soon = now + timedelta(hours=24)
    due = []
    for x in d["deadlines"]:
        try:
            at = _parse(x["at"], now)
        except (KeyError, ValueError):
            continue
        if at <= soon:
            due.append("%s %s%s%s" % (x["label"], _iso(at)[5:16], " OVERDUE" if at < now else "",
                                      (" — " + x["note"][:90]) if x.get("note") else ""))
    if due:
        out.append("deadlines ≤24h:")
        out.extend("  " + d for d in due)
    opened = [r for r in d["readouts"] if r.get("status", "open") == "open"]
    if opened:
        out.append("open readouts (%d):" % len(opened))
        for r in opened:
            try:
                age_h = (now - _parse(r["opened"], now)).total_seconds() / 3600
            except (KeyError, ValueError):
                age_h = float("nan")
            last = r.get("last") or {}
            out.append("  …%s %-28s t+%.0fh  %sv %sL%s%s" % (
                _tail(r["url"]), (r.get("label") or "")[:28], age_h, last.get("views", "?"), last.get("likes", "?"),
                (" due " + r["due"][5:16]) if r.get("due") else "", (" — " + last["note"][:60]) if last.get("note") else ""))
    if d["do_not_reply"]:
        out.append("do-not-reply (per thread — a fresh thread is eligible unless the reason says otherwise):")
        for h, v in sorted(d["do_not_reply"].items()):
            out.append("  %-13s %s" % (h, (v.get("reason") or "")[:110]))
    if d["used_angles"]:
        out.append("used angles (%d, never reuse; extend only with a NEW mechanism if the author engages):" % len(d["used_angles"]))
        line = " "
        for a in d["used_angles"]:
            piece = a[:70] + " ·"
            if len(line) + len(piece) > 100:
                out.append(line.rstrip(" ·")); line = " "
            line += " " + piece
        if line.strip(" ·"):
            out.append(line.rstrip(" ·"))
    out.append("targets: %d (%s)" % (len(d["targets"]), " ".join(d["targets"])))
    if d.get("megas"):
        out.append("megas: %d (max 1 reply/day, unique angle only — tools/targets.py)" % len(d["megas"]))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="state.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE)
    sub = ap.add_subparsers(dest="verb", required=True)
    sub.add_parser("show")
    p = sub.add_parser("cap"); p.add_argument("kind", choices=("reply", "original"))
    p = sub.add_parser("hit"); p.add_argument("handle"); p.add_argument("url")
    p = sub.add_parser("readout"); rs = p.add_subparsers(dest="op", required=True)
    q = rs.add_parser("add"); q.add_argument("url", help="URL or bare status id"); q.add_argument("label"); q.add_argument("--due"); q.add_argument("--note")
    q = rs.add_parser("touch"); q.add_argument("url"); q.add_argument("--views", type=int, required=True); q.add_argument("--likes", type=int); q.add_argument("--note")
    q = rs.add_parser("close"); q.add_argument("url"); q.add_argument("--verdict")
    p = sub.add_parser("dnr"); ds = p.add_subparsers(dest="op", required=True)
    q = ds.add_parser("add"); q.add_argument("handle"); q.add_argument("reason")
    q = ds.add_parser("clear"); q.add_argument("handle")
    p = sub.add_parser("angle"); an = p.add_subparsers(dest="op", required=True)
    q = an.add_parser("add"); q.add_argument("text")
    p = sub.add_parser("deadline"); dl = p.add_subparsers(dest="op", required=True)
    q = dl.add_parser("add"); q.add_argument("label", help="short key, e.g. [account-1]-exif-carry"); q.add_argument("at"); q.add_argument("--note")
    q = dl.add_parser("clear"); q.add_argument("label", help="exact label or unique prefix")
    p = sub.add_parser("targets"); tg = p.add_subparsers(dest="op", required=True)
    q = tg.add_parser("set"); q.add_argument("handles", nargs="+")
    a = ap.parse_args(argv)
    now = _now(); today = now.date().isoformat()
    d = load(a.file)
    _roll(d, today)
    if a.verb == "show":
        print(show(d, now)); return 0
    if a.verb == "cap":
        # Since 09-06 the x CLI consumes caps itself after each verified write
        # (xcli/caps.py). Counting here too would double-count: refuse.
        print("state.py cap: caps are counted by the x CLI now — nothing to do (see `state.py show`)", file=sys.stderr)
        return 0
    elif a.verb == "hit":
        h = a.handle.lstrip("@"); lst = d["author_hits"]["hits"].setdefault(h, [])
        if a.url not in lst:
            lst.append(a.url)
        print("%s×%d today" % (h, len(lst)))
    elif a.verb == "readout":
        r = _pick(d["readouts"], "url", a.url)
        if a.op == "add":
            if r is None:
                r = {"url": _as_url(a.url), "label": a.label, "opened": _iso(now), "due": None, "status": "open", "last": None, "verdict": None}
                d["readouts"].append(r)
            r["label"], r["status"] = a.label, "open"
            if a.due:
                r["due"] = _iso(_parse(a.due, now))
            if a.note:
                r["note"] = a.note[:120]
            print("readout open …%s %s" % (_tail(a.url), a.label))
        elif r is None:
            print("state.py: no readout for %s" % a.url, file=sys.stderr); return 2
        elif a.op == "touch":
            r["last"] = {"t": _iso(now), "views": a.views, "likes": a.likes, "note": (a.note or "")[:120] or None}
            print("readout …%s %dv%s" % (_tail(a.url), a.views, (" %dL" % a.likes) if a.likes is not None else ""))
        else:
            r["status"], r["verdict"], r["closed"] = "closed", a.verdict, _iso(now)
            print("readout closed …%s" % _tail(a.url))
    elif a.verb == "dnr":
        h = a.handle.lstrip("@")
        if a.op == "add":
            d["do_not_reply"][h] = {"reason": a.reason, "since": _iso(now)}; print("do-not-reply +%s" % h)
        else:
            d["do_not_reply"].pop(h, None); print("do-not-reply -%s" % h)
    elif a.verb == "angle":
        if a.text not in d["used_angles"]:
            d["used_angles"].append(a.text)
        print("used angles: %d" % len(d["used_angles"]))
    elif a.verb == "deadline":
        hit = _pick(d["deadlines"], "label", a.label)
        if a.op == "add":
            if hit:
                d["deadlines"].remove(hit)
            entry = {"label": a.label, "at": _iso(_parse(a.at, now))}
            if a.note:
                entry["note"] = a.note[:200]
            d["deadlines"].append(entry); print("deadline %s @ %s" % (a.label, entry["at"]))
        elif hit is None:
            print("state.py: no deadline matches %r (labels: %s)" % (a.label, ", ".join(x["label"][:30] for x in d["deadlines"])), file=sys.stderr); return 2
        else:
            d["deadlines"].remove(hit); print("deadline -%s" % hit["label"])
    elif a.verb == "targets":
        d["targets"] = [h.lstrip("@") for h in a.handles]; print("targets: %d" % len(d["targets"]))
    save(a.file, d, now)
    return 0


if __name__ == "__main__":
    sys.exit(main())
