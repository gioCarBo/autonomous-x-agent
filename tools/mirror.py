#!/usr/bin/env python3
"""mirror.py — build the public mirror of this repo: redacted, verified, one commit.

    mirror.py build OUT_DIR [--logs-since 2026-09-06] [--push REMOTE_URL]

Plan 2026-09-06 (Q21/Q30/Q31): the product is the agent, so the code, the
skills, the memory and the logs go public — in a *new* repo whose history
starts today, while this one stays the private archive. Before anything is
copied:

- accounts that blocked us and every do-not-reply handle become
  `[account-N]` (the fact may be told, the name never);
- the owner's employer becomes "the owner's employer" (terms in the
  git-ignored memory/private.json);
- logs older than --logs-since stay private (they quote third parties at
  length; the public story starts with the public repo);
- machine-local files, renders and anything git-ignored are not copied.

Then the mirror is grepped for what must not be there; any hit aborts the
build. `--push` force-pushes the single commit to the public repo the owner
created (the mirror is a snapshot, not a fork); scheduler.sh does this after
every wake or reflection that committed, with a write deploy key that exists
only on the Pi (ssh alias `github-mirror`). This tool never creates repos
or makes anything public by itself.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRIVATE = ROOT / "memory" / "private.json"
STATE = ROOT / "memory" / "state.json"
TEXT_EXT = {".md", ".py", ".sh", ".json", ".txt", ".toml", ".yaml", ".yml", ".jsonc", ".html", ".css", ".js", ".gitignore", ""}
NEVER = ("memory/private.json", "tools/agent.env")
FORBIDDEN = (
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(auth_token|ct0)\s*[=:]\s*[A-Za-z0-9%]{8,}"),
)


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True, check=True).stdout
    return [ln for ln in out.splitlines() if ln]


def load_private() -> dict:
    try:
        return json.loads(PRIVATE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def redaction_map(private: dict, state: dict) -> tuple[dict[str, str], dict[str, str]]:
    """(handle -> placeholder, term -> replacement). Blockers first so their
    numbering is stable across builds; do-not-reply handles follow."""
    handles: dict[str, str] = {}
    for h in private.get("redact_handles", []):
        handles.setdefault(h.lower(), "[account-%d]" % (len(handles) + 1))
    for h in (state.get("do_not_reply") or {}):
        handles.setdefault(h.lower(), "[account-%d]" % (len(handles) + 1))
    terms = dict(private.get("redact_terms") or {})
    for t in private.get("employer_terms", []):
        terms.setdefault(t, "the owner's employer")
    return handles, terms


def redact(text: str, handles: dict[str, str], terms: dict[str, str]) -> str:
    for h, ph in sorted(handles.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(r"@?\b" + re.escape(h) + r"\b", ph, text, flags=re.I)
    for t, rep in sorted(terms.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(r"\b" + re.escape(t) + r"\b", rep, text, flags=re.I)
    return text


def keep(path: str, logs_since: str) -> bool:
    if path in NEVER or path.startswith("renders/"):
        return False
    if path.startswith("logs/"):
        m = re.match(r"logs/(\d{4}-\d{2}-\d{2})", path)
        return bool(m) and m.group(1) >= logs_since
    return True


def verify(out: Path, handles: dict[str, str], terms: dict[str, str]) -> list[str]:
    bad = []
    pats = [re.compile(r"\b" + re.escape(h) + r"\b", re.I) for h in handles]
    pats += [re.compile(r"\b" + re.escape(t) + r"\b", re.I) for t in terms]
    pats += list(FORBIDDEN)
    for f in out.rglob("*"):
        if not f.is_file() or ".git" in f.parts:
            continue
        try:
            txt = f.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for rx in pats:
            if rx.search(txt):
                bad.append("%s: %s" % (f.relative_to(out), rx.pattern[:40]))
    return bad


def build(out: Path, logs_since: str, push: str | None = None) -> int:
    if not PRIVATE.exists():
        # Without the git-ignored terms file the employer would go out unredacted
        # (the Pi ran without it until 09-06): never build blind.
        print("mirror.py: REFUSED — %s is missing (copy it from the owner's machine)" % PRIVATE, file=sys.stderr)
        return 2
    private = load_private()
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    handles, terms = redaction_map(private, state)
    if out.exists() and any(out.iterdir()):
        print("mirror.py: %s is not empty" % out, file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    copied = skipped = 0
    for rel in tracked_files():
        if not keep(rel, logs_since):
            skipped += 1
            continue
        src, dst = ROOT / rel, out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix.lower() in TEXT_EXT:
            try:
                dst.write_text(redact(src.read_text(), handles, terms))
            except UnicodeDecodeError:
                shutil.copy2(src, dst)
        else:
            shutil.copy2(src, dst)
        copied += 1
    bad = verify(out, handles, terms)
    if bad:
        print("mirror.py: REFUSED — the mirror still contains:\n  " + "\n  ".join(bad[:30]), file=sys.stderr)
        shutil.rmtree(out)
        return 3
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=out, check=True)
    subprocess.run(["git", "add", "-A"], cwd=out, check=True)
    subprocess.run(["git", "-c", "user.name=GC agent", "-c", "user.email=agent@users.noreply.github.com",
                    "commit", "-q", "--no-verify", "-m",
                    "public mirror of the agent running @GCBullGlasses — history starts %s\n\n"
                    "Everything from here on is public: code, skills, memory, logs. Earlier logs and\n"
                    "the names of accounts that blocked or muted the account stay private." % logs_since],
                   cwd=out, check=True)
    size = subprocess.run(["du", "-sh", str(out)], capture_output=True, text=True).stdout.split()[0]
    print("mirror built at %s: %d files copied, %d skipped, %d handles and %d terms redacted, %s" % (
        out, copied, skipped, len(handles), len(terms), size))
    if push:
        # The mirror is a snapshot, not a fork: every refresh replaces the
        # remote's single commit (the scheduler does this after each wake).
        subprocess.run(["git", "remote", "add", "origin", push], cwd=out, check=True)
        subprocess.run(["git", "push", "-q", "--force", "origin", "main"], cwd=out, check=True)
        print("force-pushed to %s" % push)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mirror.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="verb", required=True)
    b = sub.add_parser("build")
    b.add_argument("out", type=Path)
    b.add_argument("--logs-since", default="2026-09-06")
    b.add_argument("--push", help="remote URL of the public mirror repo (force-pushed, one commit); omit to only build")
    a = ap.parse_args(argv)
    return build(a.out, a.logs_since, a.push)


if __name__ == "__main__":
    sys.exit(main())
