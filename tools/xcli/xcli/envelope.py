"""Output contract: one JSON envelope on stdout, human logs on stderr.

Exit codes:
  0 ok                              evidence returned
  1 verb bug (page/verification)    bug issue filed (writes) or logged
  2 infra (CDP/Chrome unreachable)  no issue — preflight domain
  3 session lost                    no issue — owner must log in on the Pi
"""

import json
import sys

OK, BUG, INFRA, SESSION = 0, 1, 2, 3


def log(msg: str) -> None:
    print(f"[xcli] {msg}", file=sys.stderr, flush=True)


def emit(action: str, evidence: dict) -> None:
    print(json.dumps({"ok": True, "action": action, "evidence": evidence},
                     ensure_ascii=False))
    sys.exit(OK)


def fail(action: str, code: int, error_code: str, message: str,
         diagnostics: dict | None = None, signature: str | None = None,
         screenshot: str | None = None, issue_url: str | None = None,
         queued: bool = False) -> None:
    envelope = {"ok": False, "action": action,
                "error": {"code": error_code, "message": message,
                          "diagnostics": diagnostics or {}}}
    err = envelope["error"]
    if signature:
        err["signature"] = signature
    if screenshot:
        err["screenshot"] = screenshot
    if issue_url:
        err["issue_url"] = issue_url
    if queued:
        err["issue_queued"] = True
    print(json.dumps(envelope, ensure_ascii=False))
    sys.exit(code)
