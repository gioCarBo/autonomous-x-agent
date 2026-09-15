"""Daily caps, enforced by the CLI itself (memory/state.json `caps`).

Until 09-06 the LLM counted its own actions (`tools/state.py cap reply`)
after each write verb — a rule that lived in a skill and depended on the
model remembering it. The Floor's ceilings (25 replies, 5 originals, 2
posts/hour, 3 follows a day) and the plan's own caps (30 likes, 2 reposts)
are now checked before a write verb touches the page and consumed after
its evidence, in the same state file `tools/state.py show` prints.

`check(kind)` -> (ok, detail); `consume(kind)`. Kinds: reply, original
(posts and quotes), like, repost, follow. A refused verb exits 1 with
error code `cap-reached` and files no bug issue: it is not a bug.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STATE = ROOT / "memory" / "state.json"

# kind -> (counter, max key, default max)
LIMITS = {
    "reply": ("replies", "reply_max", 25),
    "original": ("originals", "original_max", 5),
    "like": ("likes", "like_max", 30),
    "repost": ("reposts", "repost_max", 2),
    "follow": ("follows", "follow_max", 3),
}
POSTS_PER_HOUR = 2  # Floor: originals + quotes


def _now() -> datetime:
    return datetime.now().astimezone()


def load(path: Path = STATE) -> dict:
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except json.JSONDecodeError:
        return {}


def save(state: dict, path: Path = STATE) -> None:
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def roll(state: dict, now: datetime) -> dict:
    """Counters start from zero on a new calendar day (same rule as state.py)."""
    caps = state.setdefault("caps", {})
    today = now.date().isoformat()
    if caps.get("date") != today:
        caps["date"] = today
        for counter, _, _ in LIMITS.values():
            caps[counter] = 0
        caps["post_times"] = []
    for counter, max_key, default in LIMITS.values():
        caps.setdefault(counter, 0)
        caps.setdefault(max_key, default)
    caps.setdefault("post_times", [])
    return caps


def check(kind: str, state: dict | None = None, now: datetime | None = None) -> tuple[bool, str]:
    now = now or _now()
    state = load() if state is None else state
    caps = roll(state, now)
    counter, max_key, _ = LIMITS[kind]
    used, cap = int(caps.get(counter, 0)), int(caps.get(max_key))
    if used >= cap:
        return False, f"{counter} {used}/{cap} today"
    if kind == "original":
        recent = [t for t in caps.get("post_times", []) if _fresh(t, now)]
        if len(recent) >= POSTS_PER_HOUR:
            return False, f"{len(recent)} posts in the last hour (max {POSTS_PER_HOUR})"
    return True, f"{counter} {used + 1}/{cap}"


def _fresh(iso: str, now: datetime) -> bool:
    try:
        t = datetime.fromisoformat(iso)
    except ValueError:
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=now.tzinfo)
    return now - t < timedelta(hours=1)


def consume(kind: str, state: dict | None = None, now: datetime | None = None,
            path: Path = STATE) -> str:
    """Increment after a verified write; persists unless a state dict was
    passed in (tests)."""
    now = now or _now()
    own = state is None
    state = load(path) if own else state
    caps = roll(state, now)
    counter, max_key, _ = LIMITS[kind]
    caps[counter] = int(caps.get(counter, 0)) + 1
    if kind == "original":
        caps["post_times"] = [t for t in caps.get("post_times", []) if _fresh(t, now)]
        caps["post_times"].append(now.isoformat(timespec="minutes"))
    state["updated"] = now.isoformat(timespec="minutes")
    if own:
        save(state, path)
    return f"{counter} {caps[counter]}/{caps.get(max_key)}"
