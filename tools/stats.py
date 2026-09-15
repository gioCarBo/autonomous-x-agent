#!/usr/bin/env python3
"""stats.py — the agent's only interface to memory/stats.json.

    stats.py summary [--days 7] [--posts 12]
    stats.py record [--followers N] [--following N] [--posts-total N]
                    [--from-status FILE|-] [--kind reply|original] [--author agent|owner]

The file is append-only history, ~120 KB after a week, and every wake used
to read it whole (~25k tokens, re-sent on every turn) and then hand-edit it
(26 edits in 12 wakes). `summary` prints the two dozen lines a wake needs;
`record` upserts today's snapshot from `x status` envelopes deterministically.
Prose belongs in logs/, never here.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FILE = ROOT / "memory" / "stats.json"
METRICS = ("views", "likes", "reposts", "replies")


def _now() -> datetime:
    return datetime.now().astimezone()


def load(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {"daily": []}


def save(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _envelope_items(raw: str) -> list[dict]:
    """Accept `x status` output for one URL or many, or a bare evidence dict."""
    o = json.loads(raw)
    ev = o.get("evidence", o) if isinstance(o, dict) else o
    items = ev.get("items") if isinstance(ev, dict) and "items" in ev else [ev]
    return [i for i in items if isinstance(i, dict)]


def _items_kinds(path: Path | None = None) -> dict[str, str]:
    """url -> kind from items.json (the write verbs' authoritative tracker)."""
    f = path or (ROOT / "memory" / "items.json")
    try:
        d = json.loads(f.read_text())
    except (OSError, ValueError):
        return {}
    out = {}
    for it in d.get("items", []):
        u, k = it.get("url"), it.get("kind")
        if u and k:
            out[u] = k
    return out


def _match(posts: list[dict], item: dict) -> dict | None:
    url = item.get("url") or item.get("requested_url")
    if url:
        for p in posts:
            if p.get("url") == url:
                return p
    text = item.get("text")
    if text:
        for p in posts:
            if p.get("text") == text:
                return p
    return None


def _totals(posts: list[dict]) -> tuple[dict, float | None]:
    t = {k: sum(int(p.get(k) or 0) for p in posts) for k in METRICS}
    rate = round((t["likes"] + t["reposts"] + t["replies"]) / t["views"], 4) if t["views"] else None
    return t, rate


def record(data: dict, items: list[dict], *, today: str, now_iso: str,
           followers: int | None = None, following: int | None = None,
           posts_total: int | None = None, kind: str = "reply",
           author: str = "agent", known_kinds: dict[str, str] | None = None) -> dict:
    """Upsert today's entry. Returns a small report dict."""
    daily = data.setdefault("daily", [])
    if daily and daily[0].get("date") == today:
        day = daily[0]
    else:
        prev = daily[0] if daily else {}
        day = {"date": today,
               "followers": prev.get("followers"), "following": prev.get("following"),
               "posts_total": prev.get("posts_total"), "excluded": [],
               "recent_posts": [dict(p) for p in prev.get("recent_posts", [])],
               "totals": {}, "engagement_rate": None}
        daily.insert(0, day)
    if followers is not None:
        day["followers"] = followers
    if following is not None:
        day["following"] = following
    if posts_total is not None:
        day["posts_total"] = posts_total
    posts = day.setdefault("recent_posts", [])
    known = known_kinds or {}
    updated = added = skipped = 0
    for it in items:
        m = it.get("metrics")
        if not m or it.get("error"):
            skipped += 1
            continue
        url = it.get("url") or it.get("requested_url")
        row = _match(posts, it)
        if row is None:
            row = {"text": it.get("text"), "url": url,
                   "views": 0, "likes": 0, "reposts": 0, "replies": 0,
                   "posted_at": today, "kind": known.get(url, kind), "author": author}
            if it.get("time"):
                row["time"] = it["time"]
            posts.append(row)
            added += 1
        else:
            if not row.get("url") and url:
                row["url"] = url
            k = known.get(row.get("url"))
            if k and row.get("kind") != k:
                row["kind"] = k
            updated += 1
        for k in METRICS:
            if m.get(k) is not None:
                row[k] = int(m[k])
    day["totals"], day["engagement_rate"] = _totals(posts)
    day["measured_at"] = now_iso
    return {"date": today, "followers": day.get("followers"), "posts": len(posts),
            "updated": updated, "added": added, "skipped": skipped}


def summary(data: dict, *, days: int = 7, posts: int = 12, now: datetime | None = None) -> str:
    daily = data.get("daily", [])
    if not daily:
        return "stats.json: no data yet"
    now = now or _now()
    out = []
    latest, prev = daily[0], (daily[1] if len(daily) > 1 else None)
    win = daily[:days]
    first = win[-1]
    f_now, f_first = latest.get("followers"), first.get("followers")
    delta_w = (f_now - f_first) if isinstance(f_now, int) and isinstance(f_first, int) else None
    d_day = (f_now - prev["followers"]) if prev and isinstance(prev.get("followers"), int) and isinstance(f_now, int) else None
    out.append("followers %s (%s in %dd, %s vs prev day) · following %s · posts_total %s" % (
        f_now, f"{delta_w:+d}" if delta_w is not None else "?", len(win),
        f"{d_day:+d}" if d_day is not None else "?", latest.get("following"), latest.get("posts_total")))
    out.append("series: " + " | ".join("%s %s" % (e["date"][5:], e.get("followers")) for e in win))
    t, rate = latest.get("totals") or {}, latest.get("engagement_rate")
    pt, prate = (prev.get("totals") or {}, prev.get("engagement_rate")) if prev else ({}, None)
    out.append("window %s posts · %s views (%s) · %s likes (%s) · %s replies · eng %s (prev %s)" % (
        len(latest.get("recent_posts", [])), t.get("views"),
        f"{t.get('views', 0) - pt.get('views', 0):+d}" if pt else "n/a",
        t.get("likes"), f"{t.get('likes', 0) - pt.get('likes', 0):+d}" if pt else "n/a",
        t.get("replies"), f"{rate * 100:.2f}%" if isinstance(rate, (int, float)) else rate,
        f"{prate * 100:.2f}%" if isinstance(prate, (int, float)) else "n/a"))
    ma = latest.get("measured_at")
    if ma:
        try:
            age = now - datetime.fromisoformat(ma)
            if age > timedelta(hours=3):
                out.append("(measured %dh ago — run metrics before trusting per-post numbers)" % (age.total_seconds() // 3600))
        except ValueError:
            pass
    prev_posts = prev.get("recent_posts", []) if prev else []
    agent = [p for p in latest.get("recent_posts", []) if p.get("author", "agent") == "agent"]
    owner = [p for p in latest.get("recent_posts", []) if p.get("author") == "owner"]
    agent.sort(key=lambda p: int(p.get("views") or 0), reverse=True)
    out.append("%5s %6s %5s %4s %-8s %-5s %s" % ("views", "d24h", "likes", "repl", "kind", "date", "text"))
    for p in agent[:posts]:
        pp = _match(prev_posts, p)
        d24 = (int(p.get("views") or 0) - int(pp.get("views") or 0)) if pp else None
        out.append("%5s %6s %5s %4s %-8s %-5s %s" % (
            p.get("views"), f"{d24:+d}" if d24 is not None else "new", p.get("likes"), p.get("replies"),
            (p.get("kind") or "")[:8], (p.get("posted_at") or "")[5:], (p.get("text") or "").replace("\n", " ")[:56]))
    if len(agent) > posts:
        out.append("… %d more agent posts in window" % (len(agent) - posts))
    if owner:
        ot, _ = _totals(owner)
        out.append("owner posts in window: %d · %d views · %d likes" % (len(owner), ot["views"], ot["likes"]))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stats.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE)
    sub = ap.add_subparsers(dest="verb", required=True)
    s = sub.add_parser("summary", help="the lines a wake needs, never the file")
    s.add_argument("--days", type=int, default=7)
    s.add_argument("--posts", type=int, default=12)
    r = sub.add_parser("record", help="upsert today's snapshot from x status envelopes")
    r.add_argument("--followers", type=int)
    r.add_argument("--following", type=int)
    r.add_argument("--posts-total", type=int)
    r.add_argument("--from-status", help="file with `x status` JSON, or - for stdin")
    r.add_argument("--kind", choices=("reply", "original"), default="reply")
    r.add_argument("--author", choices=("agent", "owner"), default="agent")
    a = ap.parse_args(argv)
    data = load(a.file)
    if a.verb == "summary":
        print(summary(data, days=a.days, posts=a.posts))
        return 0
    items: list[dict] = []
    if a.from_status:
        raw = sys.stdin.read() if a.from_status == "-" else Path(a.from_status).read_text()
        try:
            items = _envelope_items(raw)
        except json.JSONDecodeError as e:
            print(f"stats.py: not a JSON envelope: {e}", file=sys.stderr)
            return 2
    if not items and a.followers is None and a.following is None and a.posts_total is None:
        print("stats.py record: nothing to record (no envelope, no counts)", file=sys.stderr)
        return 2
    now = _now()
    rep = record(data, items, today=now.date().isoformat(), now_iso=now.isoformat(timespec="minutes"),
                 followers=a.followers, following=a.following, posts_total=a.posts_total,
                 kind=a.kind, author=a.author, known_kinds=_items_kinds())
    save(a.file, data)
    print("recorded %(date)s: followers=%(followers)s posts=%(posts)d updated=%(updated)d added=%(added)d skipped=%(skipped)d" % rep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
