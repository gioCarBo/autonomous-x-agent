#!/usr/bin/env python3
"""items.py — one row per published item, measured at fixed ages.

    items.py add URL [--kind reply|original|quote] [--series NAME] [--model NAME]
                     [--parent URL] [--text TEXT] [--followers N]
    items.py add --from-envelope FILE|- ...     (the `x reply|post` envelope)
    items.py collect [--due|--all] [--dry-run]  run x profile/status/analytics, record
    items.py record --status FILE --analytics FILE [--followers N]   (pure part of collect)
    items.py mark URL --author-replied | --no-author-replied
    items.py summary [--hours 48]               the lines a wake needs
    items.py report [--days 14] [--by series|model|kind]
    items.py backfill                           import stats.json + state.json readouts once

Why: stats.json is a daily snapshot of a rolling window, so nobody could
say what a post did in its first hour versus its first day, which series or
model produced it, or whether anyone visited the profile because of it.
This file (memory/items.json) stores, per item, snapshots at t+1h, t+6h,
t+24h and t+72h with the public counters (`x status`), the Premium
analytics (`x analytics`: impressions, engagements, detail expands,
profile visits, new follows) and the account's follower count at that
moment. `collect --due` is deterministic and runs from scheduler.sh before
every wake; the LLM only ever calls `add`, `mark` and `summary`.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FILE = ROOT / "memory" / "items.json"
STATS_FILE = ROOT / "memory" / "stats.json"
STATE_FILE = ROOT / "memory" / "state.json"
XCLI = ROOT / "tools" / "xcli" / "x"
OWNER = "GCBullGlasses"
TWITTER_EPOCH_MS = 1288834974657

# checkpoint label -> (min, max) age in minutes. A reading is tagged with
# the checkpoint whose window contains its age; a checkpoint whose window
# was missed (nothing ran) stays missing forever — a 19h reading is not a
# 1h reading. The real age_min is stored on every snapshot. Past 72h the
# item is closed by its final reading.
CHECKPOINTS = (("1h", 55, 180), ("6h", 330, 900), ("24h", 1380, 2880), ("72h", 4260, None))
PUBLIC = ("views", "likes", "replies", "reposts")
ANALYTICS = ("impressions", "engagements", "detail_expands", "profile_visits",
             "new_follows", "link_clicks", "bookmarks")


def _now() -> datetime:
    return datetime.now().astimezone()


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="minutes")


def _parse(s: str, now: datetime) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=now.tzinfo)


def status_id(url: str) -> str | None:
    tail = (url or "").rstrip("/").split("/status/")
    return tail[1].split("/")[0].split("?")[0] if len(tail) == 2 and tail[1][:1].isdigit() else None


def snowflake_time(sid: str | None) -> datetime | None:
    try:
        ms = (int(sid) >> 22) + TWITTER_EPOCH_MS
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def load(path: Path) -> dict:
    if path.exists():
        d = json.loads(path.read_text())
    else:
        d = {}
    d.setdefault("version", 1)
    d.setdefault("items", [])
    return d


def save(path: Path, d: dict, now: datetime) -> None:
    d["updated"] = _iso(now)
    path.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n")


def find(d: dict, url_or_id: str) -> dict | None:
    sid = status_id(url_or_id) or (url_or_id if url_or_id.isdigit() else None)
    for it in d["items"]:
        if it["url"] == url_or_id or (sid and it["status_id"] == sid):
            return it
    if sid is None:
        return None
    tail = [it for it in d["items"] if it["status_id"].endswith(sid)]
    return tail[0] if len(tail) == 1 else None


# --- add ------------------------------------------------------------------------

def _envelope_evidence(raw: str) -> dict:
    o = json.loads(raw)
    return o.get("evidence", o) if isinstance(o, dict) else {}


def _short_model(model: str | None) -> str | None:
    """Canonical short model name: 'zai-coding-plan/glm-5.3-flash' -> 'glm-5.3-flash'.

    The A/B readout groups by this string; full provider ids and bare names
    must not land as two different arms (2026-09-07 reflection)."""
    if not model:
        return None
    return model.strip().split("/")[-1] or None


def add(d: dict, url: str, *, now: datetime, kind: str = "reply", series: str | None = None,
        model: str | None = None, parent: str | None = None, text: str | None = None,
        followers: int | None = None, wake: str | None = None) -> tuple[dict, bool]:
    """Upsert one item. Returns (item, created)."""
    sid = status_id(url)
    if not sid:
        raise ValueError(f"not a status URL: {url}")
    model = _short_model(model)
    it = find(d, sid)
    created = it is None
    if created:
        pub = snowflake_time(sid) or now
        it = {"url": url, "status_id": sid, "kind": kind, "series": series, "model": model,
              "parent_url": parent, "parent_handle": _handle(parent),
              "text": (text or "")[:200] or None,
              "published": _iso(pub.astimezone(now.tzinfo)),
              "followers_at_publish": followers, "author_replied": None,
              "snapshots": [], "closed": False}
        d["items"].append(it)
    else:
        if series:
            it["series"] = series
        if model:
            it["model"] = model
        if parent:
            it["parent_url"], it["parent_handle"] = parent, _handle(parent)
        if text and not it.get("text"):
            it["text"] = text[:200]
        if followers is not None and it.get("followers_at_publish") is None:
            it["followers_at_publish"] = followers
        if kind and kind != "reply":
            it["kind"] = kind
    if wake:
        it["wake"] = wake
    return it, created


def _handle(url: str | None) -> str | None:
    if not url:
        return None
    parts = url.split("x.com/")
    h = parts[1].split("/")[0] if len(parts) == 2 else None
    return None if h in (None, "", "i") else h


# --- collect --------------------------------------------------------------------

def age_min(it: dict, now: datetime) -> float:
    return (now - _parse(it["published"], now)).total_seconds() / 60


def next_checkpoint(it: dict, now: datetime) -> str | None:
    """The checkpoint whose window contains the item's age now, unless the
    item already has it. Outside every window: nothing is due."""
    have = {s.get("checkpoint") for s in it["snapshots"]}
    age = age_min(it, now)
    for label, lo, hi in CHECKPOINTS:
        if lo <= age and (hi is None or age <= hi):
            return None if label in have else label
    return None


def due(d: dict, now: datetime) -> list[dict]:
    return [it for it in d["items"] if not it.get("closed") and next_checkpoint(it, now)]


def record(d: dict, *, now: datetime, status_items: list[dict], analytics_items: list[dict],
           followers: int | None, only: set[str] | None = None) -> dict:
    """Merge one collection round into snapshots. Pure."""
    by_sid_status = {status_id(i.get("url") or i.get("requested_url") or ""): i
                     for i in status_items if not i.get("error")}
    by_sid_an = {i.get("status_id") or status_id(i.get("requested_url") or ""): i
                 for i in analytics_items if not i.get("error")}
    touched, closed = 0, 0
    for it in d["items"]:
        sid = it["status_id"]
        if only is not None and sid not in only:
            continue
        st, an = by_sid_status.get(sid), by_sid_an.get(sid)
        if st is None and an is None:
            continue
        snap = {"t": _iso(now), "age_min": int(age_min(it, now)),
                "checkpoint": next_checkpoint(it, now), "followers": followers}
        if st is not None:
            m = st.get("metrics") or {}
            for k in PUBLIC:
                snap[k] = m.get(k)
            if it.get("text") is None and st.get("text"):
                it["text"] = st["text"][:200]
        if an is not None:
            for k in ANALYTICS:
                v = (an.get("analytics") or {}).get(k)
                if v is not None:
                    snap[k] = v
        it["snapshots"].append(snap)
        touched += 1
        if snap["checkpoint"] == CHECKPOINTS[-1][0]:
            it["closed"] = True
            closed += 1
    return {"touched": touched, "closed": closed, "followers": followers}


def run_verb(args: list[str], timeout: float) -> dict | None:
    try:
        p = subprocess.run([str(XCLI), *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        print("[items] %s failed: %s" % (args[0], e), file=sys.stderr)
        return None
    if p.stderr:
        sys.stderr.write(p.stderr)
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout.strip().splitlines()[-1]).get("evidence")
    except (json.JSONDecodeError, IndexError, AttributeError):
        return None


def _count(s) -> int | None:
    if s is None:
        return None
    if isinstance(s, int):
        return s
    s = str(s).strip().replace(" ", "")
    mult = 1
    if s[-1:] in "KkMm" and s:
        mult = 1000 if s[-1] in "Kk" else 1000000
        s = s[:-1]
    s = s.replace(".", "").replace(",", "") if mult == 1 else s.replace(",", ".")
    try:
        return int(float(s) * mult)
    except ValueError:
        return None


def collect(d: dict, *, now: datetime, everything: bool, runner=run_verb, dry_run: bool = False) -> dict:
    todo = [it for it in d["items"] if not it.get("closed")] if everything else due(d, now)
    if not todo:
        return {"touched": 0, "closed": 0, "followers": None, "due": 0}
    urls = [it["url"] for it in todo]
    if dry_run:
        return {"due": len(urls), "urls": urls}
    prof = runner(["profile", OWNER], 120)
    followers = _count(((prof or {}).get("counts") or {}).get("followers")) if prof else None
    st = runner(["status", *urls], 60 + 20 * len(urls)) or {}
    an = runner(["analytics", *urls], 60 + 25 * len(urls)) or {}
    st_items = st.get("items") if "items" in st else ([st] if st else [])
    rep = record(d, now=now, status_items=st_items or [], analytics_items=an.get("items") or [],
                 followers=followers, only={it["status_id"] for it in todo})
    rep["due"] = len(urls)
    return rep


# --- read back --------------------------------------------------------------------

def _snap(it: dict, label: str) -> dict | None:
    for s in it["snapshots"]:
        if s.get("checkpoint") == label:
            return s
    return None


def _latest(it: dict) -> dict | None:
    return it["snapshots"][-1] if it["snapshots"] else None


def summary(d: dict, *, now: datetime, hours: int = 48) -> str:
    since = now - timedelta(hours=hours)
    rows = [it for it in d["items"] if _parse(it["published"], now) >= since]
    rows.sort(key=lambda it: it["published"], reverse=True)
    open_n = len([it for it in d["items"] if not it.get("closed")])
    out = ["items: %d in %dh · %d still measuring · next collect runs before the next wake" % (len(rows), hours, open_n)]
    if not rows:
        return "\n".join(out)
    out.append("%-5s %-8s %-9s %-13s %6s %6s %6s %5s %s" % ("age", "kind", "series", "model", "v@1h", "v@24h", "v@last", "pv", "text"))
    for it in rows:
        s1, s24, sl = _snap(it, "1h"), _snap(it, "24h"), _latest(it)
        pv = (sl or {}).get("profile_visits")
        age = age_min(it, now)
        age_s = "%dm" % age if age < 120 else "%dh" % (age / 60)
        out.append("%-5s %-8s %-9s %-13s %6s %6s %6s %5s %s" % (
            age_s, it["kind"][:8], (it.get("series") or "-")[:9], _short_model(it.get("model")) or "-",
            _fmt((s1 or {}).get("views")), _fmt((s24 or {}).get("views")), _fmt((sl or {}).get("views")),
            _fmt(pv), (it.get("text") or "").replace("\n", " ")[:40]))
    return "\n".join(out)


def _fmt(v) -> str:
    return "·" if v is None else str(v)


def _median(vals: list) -> str:
    vals = [v for v in vals if isinstance(v, (int, float))]
    return "·" if not vals else str(int(statistics.median(vals)))


def report(d: dict, *, now: datetime, days: int = 14, by: str = "series") -> str:
    since = now - timedelta(days=days)
    rows = [it for it in d["items"] if _parse(it["published"], now) >= since]
    groups: dict[str, list[dict]] = {}
    for it in rows:
        key = it.get(by) or ("-" if by != "kind" else it["kind"])
        if by == "model":
            key = _short_model(it.get("model")) or "-"
        groups.setdefault(str(key), []).append(it)
    out = ["report %dd by %s: %d items" % (days, by, len(rows))]
    out.append("%-14s %3s %6s %6s %6s %5s %5s %5s %6s" % (by, "n", "v@1h", "v@24h", "imp@24", "L@24", "R@24", "pv@24", "n1h/24"))
    for key, its in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        s1 = [_snap(it, "1h") or {} for it in its]
        s24 = [_snap(it, "24h") or {} for it in its]
        out.append("%-14s %3d %6s %6s %6s %5s %5s %5s %3d/%-3d" % (
            key[-14:], len(its),
            _median([s.get("views") for s in s1]), _median([s.get("views") for s in s24]),
            _median([s.get("impressions") for s in s24]), _median([s.get("likes") for s in s24]),
            _median([s.get("replies") for s in s24]), _median([s.get("profile_visits") for s in s24]),
            len([s for s in s1 if s]), len([s for s in s24 if s])))
    # follower attribution: profile visits summed over items with a 24h snapshot
    pv = sum((_snap(it, "24h") or {}).get("profile_visits") or 0 for it in rows)
    fol = [(it.get("followers_at_publish"), (_snap(it, "24h") or {}).get("followers")) for it in rows]
    fol = [(a, b) for a, b in fol if isinstance(a, int) and isinstance(b, int)]
    if fol:
        out.append("profile visits @24h summed: %d · followers at publish→24h: %s" % (
            pv, ", ".join("%+d" % (b - a) for a, b in fol[:12])))
    replies = [it for it in rows if it["kind"] == "reply"]
    if replies:
        known = [it for it in replies if it.get("author_replied") is not None]
        yes = len([it for it in known if it["author_replied"]])
        out.append("author replied: %d/%d marked (%d replies unmarked)" % (yes, len(known), len(replies) - len(known)))
    return "\n".join(out)


# --- backfill ---------------------------------------------------------------------

def backfill(d: dict, stats: dict, *, now: datetime) -> int:
    """Import the rolling window of stats.json once, so the report has the
    history that exists (daily rows become untagged snapshots)."""
    n = 0
    for day in reversed(stats.get("daily", [])):
        try:
            when = datetime.fromisoformat(day.get("measured_at") or (day["date"] + "T23:00")).astimezone(now.tzinfo)
        except ValueError:
            continue
        for p in day.get("recent_posts", []):
            if p.get("author", "agent") != "agent" or not status_id(p.get("url") or ""):
                continue
            it, created = add(d, p["url"], now=now, kind=p.get("kind") or "reply", text=p.get("text"))
            if created:
                it["backfilled"] = True
                n += 1
            snap = {"t": _iso(when), "age_min": int((when - _parse(it["published"], now)).total_seconds() / 60),
                    "checkpoint": None, "followers": day.get("followers")}
            if snap["age_min"] < 0:
                continue
            for k in PUBLIC:
                snap[k] = p.get(k)
            if not any(s["t"] == snap["t"] for s in it["snapshots"]):
                it["snapshots"].append(snap)
    for it in d["items"]:
        it["snapshots"].sort(key=lambda s: s["t"])
    return n


def backfill_readouts(d: dict, state: dict, *, now: datetime) -> int:
    """state.json readouts carry the URLs of our tracked posts (with their
    label and last reading) — the rows stats.json lost when it matched by
    text. One untagged snapshot per readout with a `last` reading."""
    n = 0
    for r in state.get("readouts") or []:
        url = r.get("url") or ""
        if not status_id(url):
            continue
        label = (r.get("label") or "").lower()
        kind = "original" if any(k in label for k in ("original", "announce", "diary", "ab-", "a/b")) else "reply"
        it, created = add(d, url, now=now, kind=kind, text=r.get("note") or r.get("label"))
        if created:
            it["backfilled"], it["label"] = True, r.get("label")
            n += 1
        last = r.get("last") or {}
        if last.get("t") and isinstance(last.get("views"), int):
            try:
                when = _parse(last["t"], now)
            except ValueError:
                continue
            snap = {"t": _iso(when), "age_min": int((when - _parse(it["published"], now)).total_seconds() / 60),
                    "checkpoint": None, "followers": None, "views": last.get("views"), "likes": last.get("likes")}
            if snap["age_min"] >= 0 and not any(s["t"] == snap["t"] for s in it["snapshots"]):
                it["snapshots"].append(snap)
                it["snapshots"].sort(key=lambda s: s["t"])
    return n


# --- main --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="items.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE)
    sub = ap.add_subparsers(dest="verb", required=True)
    a = sub.add_parser("add", help="start measuring one published item")
    a.add_argument("url", nargs="?")
    a.add_argument("--from-envelope", help="`x reply|post` envelope file, or - for stdin")
    a.add_argument("--kind", choices=("reply", "original", "quote"), default="reply")
    a.add_argument("--series", help="metrics|postmortem|take|… (originals)")
    a.add_argument("--model", default=os.environ.get("X_AGENT_MODEL"),
                   help="writing model; defaults to $X_AGENT_MODEL")
    a.add_argument("--parent", help="parent post URL (replies, quotes)")
    a.add_argument("--text")
    a.add_argument("--followers", type=int, help="follower count at publish")
    a.add_argument("--wake", help="wake label, e.g. 2026-09-06-1500")
    c = sub.add_parser("collect", help="measure due items through the x CLI (scheduler)")
    g = c.add_mutually_exclusive_group()
    g.add_argument("--due", action="store_true", default=True)
    g.add_argument("--all", action="store_true")
    c.add_argument("--dry-run", action="store_true")
    r = sub.add_parser("record", help="merge saved envelopes (tests, manual)")
    r.add_argument("--status"); r.add_argument("--analytics"); r.add_argument("--followers", type=int)
    m = sub.add_parser("mark", help="did the parent author reply to us?")
    m.add_argument("url")
    mg = m.add_mutually_exclusive_group(required=True)
    mg.add_argument("--author-replied", action="store_true")
    mg.add_argument("--no-author-replied", action="store_true")
    s = sub.add_parser("summary"); s.add_argument("--hours", type=int, default=48)
    rp = sub.add_parser("report"); rp.add_argument("--days", type=int, default=14)
    rp.add_argument("--by", choices=("series", "model", "kind"), default="series")
    sub.add_parser("backfill", help="import stats.json history once")
    args = ap.parse_args(argv)

    now = _now()
    d = load(args.file)
    if args.verb == "add":
        url, text, parent = args.url, args.text, args.parent
        if args.from_envelope:
            raw = sys.stdin.read() if args.from_envelope == "-" else Path(args.from_envelope).read_text()
            ev = _envelope_evidence(raw)
            url = url or ev.get("url")
            text = text or ev.get("text")
            if ev.get("checked"):
                print("items.py: envelope is a --check run, nothing published", file=sys.stderr)
                return 2
        if not url:
            print("items.py add: need a URL or a publish envelope", file=sys.stderr)
            return 2
        try:
            it, created = add(d, url, now=now, kind=args.kind, series=args.series, model=args.model,
                              parent=parent, text=text, followers=args.followers, wake=args.wake)
        except ValueError as e:
            print("items.py: %s" % e, file=sys.stderr)
            return 2
        save(args.file, d, now)
        print("item %s …%s %s%s%s" % ("added" if created else "updated", it["status_id"][-8:], it["kind"],
                                      (" " + it["series"]) if it.get("series") else "",
                                      (" " + it["model"]) if it.get("model") else ""))
        return 0
    if args.verb == "collect":
        rep = collect(d, now=now, everything=args.all, dry_run=args.dry_run)
        if not args.dry_run and rep.get("touched"):
            save(args.file, d, now)
        print("[items] collect: due=%s touched=%s closed=%s followers=%s" % (
            rep.get("due"), rep.get("touched", 0), rep.get("closed", 0), rep.get("followers")), file=sys.stderr)
        print(json.dumps(rep))
        return 0
    if args.verb == "record":
        st = _envelope_evidence(Path(args.status).read_text()) if args.status else {}
        an = _envelope_evidence(Path(args.analytics).read_text()) if args.analytics else {}
        st_items = st.get("items") if "items" in st else ([st] if st else [])
        rep = record(d, now=now, status_items=st_items or [], analytics_items=an.get("items") or [],
                     followers=args.followers)
        save(args.file, d, now)
        print(json.dumps(rep))
        return 0
    if args.verb == "mark":
        it = find(d, args.url)
        if it is None:
            print("items.py: no item for %s" % args.url, file=sys.stderr)
            return 2
        it["author_replied"] = bool(args.author_replied)
        save(args.file, d, now)
        print("…%s author_replied=%s" % (it["status_id"][-8:], it["author_replied"]))
        return 0
    if args.verb == "summary":
        print(summary(d, now=now, hours=args.hours))
        return 0
    if args.verb == "report":
        print(report(d, now=now, days=args.days, by=args.by))
        return 0
    if args.verb == "backfill":
        stats = json.loads(STATS_FILE.read_text()) if STATS_FILE.exists() else {}
        state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
        n = backfill(d, stats, now=now) + backfill_readouts(d, state, now=now)
        save(args.file, d, now)
        print("backfilled %d items (%d total)" % (n, len(d["items"])))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
