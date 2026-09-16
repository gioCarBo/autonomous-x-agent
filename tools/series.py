#!/usr/bin/env python3
"""series.py — the fixed daily series and the model each slot writes with.

    series.py show                       slots, today's status, next model per series
    series.py due [--horizon-min 65]     slots due now (JSON list) — precheck/scheduler
    series.py model [SERIES]             the model for this wake: alternates per series,
                                         default model when no series is due
    series.py set-default PROVIDER/MODEL | series.py set-arms SERIES A B

Plan 2026-09-06: three fixed originals a day (metrics card in the morning,
one sharp take at midday, a postmortem card in the evening) and, for two
weeks, originals alternate between two writing models *within each
series*. The LLM cannot alternate itself — every wake is one model — so
the scheduler asks this tool which slot is due and which model it gets,
then launches `opencode run --model …` with it. A slot is "done" for the
day when memory/items.json holds an item with that series published today,
which is what the write verb records; nothing here depends on the LLM
remembering anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FILE = ROOT / "memory" / "series.json"
ITEMS = ROOT / "memory" / "items.json"

DEFAULT = {
    "version": 1,
    "default_model": "zai-coding-plan/glm-5.3-flash",
    "ab_until": "2026-09-20",
    "series": {
        "metrics": {"at": "07:30", "arms": ["zai-coding-plan/glm-5.3-flash", "zai-coding-plan/glm-5.3"], "last": None,
                    "what": "the daily followers card (render.py metrics) + 1-2 lines on what the number says"},
        "take": {"at": "13:00", "arms": ["zai-coding-plan/glm-5.3-flash", "zai-coding-plan/glm-5.3"], "last": None,
                 "what": "one sharp take on a thread of the day: plain text or a quote, one idea, addressed to someone"},
        "postmortem": {"at": "21:30", "arms": ["zai-coding-plan/glm-5.3-flash", "zai-coding-plan/glm-5.3"], "last": None,
                       "what": "what I got wrong today (render.py card) + the one thing that changes tomorrow"},
    },
}


def _now() -> datetime:
    return datetime.now().astimezone()


def load(path: Path = DEFAULT_FILE) -> dict:
    d = json.loads(path.read_text()) if path.exists() else {}
    for k, v in DEFAULT.items():
        d.setdefault(k, json.loads(json.dumps(v)))
    return d


def save(d: dict, path: Path = DEFAULT_FILE, now: datetime | None = None) -> None:
    d["updated"] = (now or _now()).isoformat(timespec="minutes")
    path.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n")


def _slot_time(spec: str, now: datetime) -> datetime:
    hh, mm = (int(x) for x in spec.split(":"))
    return now.replace(hour=hh, minute=mm, second=0, microsecond=0)


def done_today(items: dict, series: str, now: datetime) -> bool:
    today = now.date()
    for it in items.get("items", []):
        if it.get("series") != series:
            continue
        try:
            pub = datetime.fromisoformat(it["published"]).astimezone(now.tzinfo)
        except (KeyError, ValueError):
            continue
        if pub.date() == today:
            return True
    return False


def due(d: dict, items: dict, now: datetime, horizon_min: int = 65, grace_h: int = 6) -> list[str]:
    """Series whose slot is within the horizon (or up to grace_h late) and
    which have not been posted today. Late slots are still due: a metrics
    card at 10:00 beats none; one at 16:00 is yesterday's news."""
    out = []
    for name, spec in d["series"].items():
        at = _slot_time(spec["at"], now)
        if at - timedelta(minutes=horizon_min) <= now <= at + timedelta(hours=grace_h) \
                and not done_today(items, name, now):
            out.append(name)
    return out


def next_model(d: dict, series: str | None, now: datetime) -> str:
    """The arm this slot gets; alternates from the series' last one. After
    `ab_until` every slot uses the default model."""
    if not series or series not in d["series"]:
        return d["default_model"]
    spec = d["series"][series]
    try:
        ab_on = now.date() <= datetime.fromisoformat(d["ab_until"]).date()
    except ValueError:
        ab_on = True
    arms = spec.get("arms") or [d["default_model"]]
    if not ab_on:
        return d["default_model"]
    if len(arms) < 2:
        return arms[0]
    last = spec.get("last")
    if last in arms:
        return arms[(arms.index(last) + 1) % len(arms)]
    return arms[0]


def pick(d: dict, series: str, now: datetime) -> str:
    """Decide and record the arm for this slot (the scheduler calls this
    once per launch; a wake that ends up not posting still burned its
    turn — the next slot of that series gets the other arm, which keeps
    the two arms interleaved instead of stuck)."""
    m = next_model(d, series, now)
    d["series"][series]["last"] = m
    d["series"][series]["last_at"] = now.isoformat(timespec="minutes")
    return m


def show(d: dict, items: dict, now: datetime) -> str:
    out = ["series (default model %s · A/B until %s):" % (d["default_model"], d["ab_until"])]
    for name, spec in d["series"].items():
        status = "posted" if done_today(items, name, now) else ("DUE" if name in due(d, items, now) else "later")
        out.append("  %-11s %s  %-7s next model %-24s last %s" % (
            name, spec["at"], status, next_model(d, name, now), (spec.get("last") or "-").split("/")[-1]))
        out.append("              %s" % spec.get("what", ""))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="series.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE)
    ap.add_argument("--items", type=Path, default=ITEMS)
    sub = ap.add_subparsers(dest="verb", required=True)
    sub.add_parser("show")
    dd = sub.add_parser("due"); dd.add_argument("--horizon-min", type=int, default=65)
    m = sub.add_parser("model", help="print the model for this wake; with SERIES, record the pick")
    m.add_argument("series", nargs="?")
    sd = sub.add_parser("set-default"); sd.add_argument("model")
    sa = sub.add_parser("set-arms"); sa.add_argument("series"); sa.add_argument("a"); sa.add_argument("b")
    a = ap.parse_args(argv)
    now = _now()
    d = load(a.file)
    items = json.loads(a.items.read_text()) if a.items.exists() else {}
    if a.verb == "show":
        print(show(d, items, now)); return 0
    if a.verb == "due":
        print(json.dumps(due(d, items, now, a.horizon_min))); return 0
    if a.verb == "model":
        if a.series:
            if a.series not in d["series"]:
                print("series.py: unknown series %s" % a.series, file=sys.stderr); return 2
            print(pick(d, a.series, now)); save(d, a.file, now)
        else:
            print(d["default_model"])
        return 0
    if a.verb == "set-default":
        d["default_model"] = a.model; save(d, a.file, now); print("default model %s" % a.model); return 0
    if a.verb == "set-arms":
        d["series"][a.series]["arms"] = [a.a, a.b]; save(d, a.file, now); print("%s arms: %s | %s" % (a.series, a.a, a.b)); return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
