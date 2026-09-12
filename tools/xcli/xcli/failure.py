"""Failure semantics: screenshot, deduplicated bug issue, pending queue.

Rule (ADR 0001): a failed WRITE verb files a bug issue — one issue per
error signature, updated on recurrence, never a fallback retry. Infra and
session failures do not file issues (ops domain, not CLI bugs). Read verbs
log only; their flakes cost information, not state.

If `gh` is unavailable (network, auth), the issue request is appended to
logs/pending-issues.jsonl and retried on the next xcli invocation.
"""

import datetime
import json
import os
import subprocess
from pathlib import Path

from . import envelope

REPO = "gioCarBo/x_influencer"
DIAGNOSTICS_DIR = "logs/diagnostics"
PENDING = "logs/pending-issues.jsonl"


def _issues_enabled() -> bool:
    """Test hook: XCLI_NO_ISSUE=1 skips tracker writes entirely."""
    return os.environ.get("XCLI_NO_ISSUE") != "1"


def _now() -> str:
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def save_screenshot(cdp_session, signature: str) -> str | None:
    if cdp_session is None:
        return None
    try:
        png = cdp_session.screenshot_png()
        d = Path(DIAGNOSTICS_DIR)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{signature}-{_now()}.png"
        path.write_bytes(png)
        return str(path)
    except Exception as e:
        envelope.log(f"screenshot failed: {e}")
        return None


def _gh(args: list[str]) -> tuple[bool, str]:
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True,
                           timeout=30)
        return r.returncode == 0, (r.stdout or r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)


def _issue_body(action: str, error_code: str, message: str,
                diagnostics: dict, screenshot: str | None,
                occurrence: int) -> str:
    lines = [
        f"**Verb**: `{action}`",
        f"**Error code**: `{error_code}`",
        f"**Occurrences**: {occurrence}",
        f"**Last seen**: {_now()}",
        "",
        message,
        "",
        "```json",
        json.dumps(diagnostics, ensure_ascii=False, indent=2)[:3000],
        "```",
    ]
    if screenshot:
        lines += ["", f"Screenshot: `{screenshot}` (on the Pi)"]
    lines += ["", "The agent is blocked on this verb until fixed (ADR 0001)."]
    return "\n".join(lines)


def _search_open_issue(signature: str) -> str | None:
    """The open issue carrying this signature, matched on its exact title.

    Used to go through GitHub search (`--search '"xcli: sig" in title'`),
    whose index lags new issues and tokenizes `reply:no-modal` oddly: on
    2026-09-06 the second no-modal failure, 29 minutes after #17, did not
    find it and opened #18. Listing open issues and comparing titles here is
    deterministic."""
    ok, out = _gh(["issue", "list", "-R", REPO, "--state", "open",
                   "--json", "number,title", "--limit", "100"])
    if not ok:
        return None
    try:
        for it in json.loads(out):
            if it.get("title") == f"xcli: {signature}":
                return f"https://github.com/{REPO}/issues/{it['number']}"
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    return None


def _queue(action: str, signature: str, title: str, body: str) -> None:
    p = Path(PENDING)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps({"action": action, "signature": signature,
                            "title": title, "body": body,
                            "queued_at": _now()}) + "\n")
    envelope.log(f"gh unavailable — issue request queued in {PENDING}")


def flush_pending() -> None:
    p = Path(PENDING)
    if not p.exists():
        return
    remaining = []
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        ok, out = _gh(["issue", "create", "-R", REPO, "--title", item["title"],
                       "--body", item["body"]])
        if ok:
            envelope.log(f"flushed queued issue: {out}")
        else:
            item["retries"] = item.get("retries", 0) + 1
            remaining.append(json.dumps(item))
    p.write_text("\n".join(remaining) + ("\n" if remaining else ""))


def report_bug(action: str, signature: str, error_code: str, message: str,
               diagnostics: dict, screenshot: str | None) -> dict:
    """Create or update the deduplicated issue. Returns envelope fields."""
    if not _issues_enabled():
        envelope.log("XCLI_NO_ISSUE set — bug issue skipped")
        return {}
    occurrence = diagnostics.pop("_occurrence", 1)
    title = f"xcli: {signature}"
    body = _issue_body(action, error_code, message, diagnostics, screenshot,
                       occurrence)
    existing = _search_open_issue(signature)
    if existing:
        ok, out = _gh(["issue", "comment", existing.rsplit("/", 1)[-1], "-R",
                       REPO, "--body", body])
        if ok:
            return {"issue_url": existing}
        _queue(action, signature,
               f"{title} (comment failed, occurrence {occurrence})", body)
        return {"issue_url": existing, "issue_queued": True}
    ok, out = _gh(["issue", "create", "-R", REPO, "--title", title,
                   "--body", body])
    if ok:
        return {"issue_url": out}
    _queue(action, signature, title, body)
    return {"issue_queued": True}
