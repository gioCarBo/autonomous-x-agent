#!/usr/bin/env python3
"""rate.py — the owner's ratings of published posts (plan Q26, 2026-09-06).

    rate.py add URL SCORE "one line why"     SCORE 1-10
    rate.py show [--days 14]                 ratings + mean, joined to items.json
    rate.py pending [--n 10]                 the last unrated originals/replies to rate

Giovanni rates ~10 posts a week; the weekly reflection reads them next to
the per-item metrics (tools/items.py report). This is what makes the "8/10
voice" target a rule someone applies rather than a sentence in MEMORY.md.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FILE = ROOT / "memory" / "ratings.json"
ITEMS = ROOT / "memory" / "items.json"


def _now() -> datetime:
    return datetime.now().astimezone()


def load(path: Path = DEFAULT_FILE) -> dict:
    d = json.loads(path.read_text()) if path.exists() else {}
    d.setdefault("ratings", [])
    return d


def save(d: dict, path: Path = DEFAULT_FILE) -> None:
    path.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n")


def status_id(url: str) -> str | None:
    parts = (url or "").rstrip("/").split("/status/")
    return parts[1].split("/")[0] if len(parts) == 2 else (url if url.isdigit() else None)


def add(d: dict, url: str, score: int, why: str, now: datetime) -> dict:
    if not 1 <= score <= 10:
        raise ValueError("score must be 1-10")
    sid = status_id(url)
    if not sid:
        raise ValueError("not a status URL or id: %s" % url)
    for r in d["ratings"]:
        if r["status_id"] == sid:
            r.update({"score": score, "why": why[:200], "t": now.isoformat(timespec="minutes")})
            return r
    r = {"status_id": sid, "url": url, "score": score, "why": why[:200], "t": now.isoformat(timespec="minutes")}
    d["ratings"].append(r)
    return r


def show(d: dict, items: dict, now: datetime, days: int = 14) -> str:
    since = now - timedelta(days=days)
    by_sid = {it["status_id"]: it for it in items.get("items", [])}
    rows = [r for r in d["ratings"] if datetime.fromisoformat(r["t"]) >= since]
    if not rows:
        return "ratings: none in %dd" % days
    out = ["ratings %dd: %d · mean %.1f" % (days, len(rows), statistics.mean(r["score"] for r in rows))]
    for r in sorted(rows, key=lambda r: r["t"], reverse=True):
        it = by_sid.get(r["status_id"], {})
        out.append("%2d  %-8s %-10s %-13s %s — %s" % (
            r["score"], (it.get("kind") or "?")[:8], (it.get("series") or "-")[:10], (it.get("model") or "-").split("/")[-1][-13:],
            (it.get("text") or r["url"]).replace("\n", " ")[:44], r["why"][:60]))
    by_model: dict[str, list[int]] = {}
    for r in rows:
        m = (by_sid.get(r["status_id"], {}).get("model") or "-").split("/")[-1]
        by_model.setdefault(m, []).append(r["score"])
    if len(by_model) > 1:
        out.append("by model: " + " · ".join("%s %.1f (n=%d)" % (m, statistics.mean(v), len(v)) for m, v in sorted(by_model.items())))
    return "\n".join(out)


def pending(d: dict, items: dict, n: int = 10) -> str:
    rated = {r["status_id"] for r in d["ratings"]}
    rows = [it for it in items.get("items", []) if it["status_id"] not in rated]
    rows.sort(key=lambda it: it["published"], reverse=True)
    if not rows:
        return "nothing to rate"
    out = ["unrated (%d shown of %d) — rate.py add <url> <1-10> \"why\"" % (min(n, len(rows)), len(rows))]
    for it in rows[:n]:
        out.append("%s  %-8s %-10s %s" % (it["url"], it["kind"][:8], (it.get("series") or "-")[:10], (it.get("text") or "").replace("\n", " ")[:60]))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rate.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE)
    ap.add_argument("--items", type=Path, default=ITEMS)
    sub = ap.add_subparsers(dest="verb", required=True)
    a = sub.add_parser("add"); a.add_argument("url"); a.add_argument("score", type=int); a.add_argument("why")
    s = sub.add_parser("show"); s.add_argument("--days", type=int, default=14)
    p = sub.add_parser("pending"); p.add_argument("--n", type=int, default=10)
    args = ap.parse_args(argv)
    d = load(args.file)
    items = json.loads(args.items.read_text()) if args.items.exists() else {}
    now = _now()
    if args.verb == "add":
        try:
            r = add(d, args.url, args.score, args.why, now)
        except ValueError as e:
            print("rate.py: %s" % e, file=sys.stderr); return 2
        save(d, args.file); print("rated …%s %d/10" % (r["status_id"][-8:], r["score"])); return 0
    if args.verb == "show":
        print(show(d, items, now, args.days)); return 0
    print(pending(d, items, args.n)); return 0


if __name__ == "__main__":
    sys.exit(main())
