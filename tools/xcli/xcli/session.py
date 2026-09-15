"""Shared session helper: one CDP tab on the agent Chrome, X-locale safe."""

import json
import os
import time
import urllib.request

from .cdp import CdpError, CdpSession


def cdp_base_url() -> str:
    env = os.environ.get("BU_CDP_URL", "http://127.0.0.1:9223")
    return env.rstrip("/")


def cdp_reachable(base: str | None = None) -> bool:
    try:
        with urllib.request.urlopen((base or cdp_base_url()) + "/json/version",
                                    timeout=5) as r:
            return r.status == 200
    except (OSError, urllib.error.URLError):
        return False


OWNER_HANDLE = "GCBullGlasses"


def open_tab(start_url: str, action: str = "session") -> CdpSession:
    base = cdp_base_url()
    if not cdp_reachable(base):
        from . import envelope
        envelope.fail(action, envelope.INFRA, "cdp-unreachable",
                      f"CDP endpoint {base} is down — run preflight or "
                      "restart chrome-agent-x.service",
                      diagnostics={"base": base})
    return CdpSession(base, start_url)


_NAV_EXPR = """(() => {
  const link = document.querySelector('a[data-testid="AppTabBar_Profile_Link"]');
  const login = document.querySelector('[data-testid="loginButton"]');
  return JSON.stringify({handle: link ? link.getAttribute('href') : null,
                         loginBtn: !!login});
})()"""


def who_am_i(cdp: CdpSession) -> dict:
    """Return {handle, authed, login_btn} from the x.com nav.

    Verified against x.com/home first. X sometimes serves home as an
    empty shell (complete, but no title/nav; first seen 09-04) while
    every other x.com page renders fine — so an ambiguous home read
    (no handle AND no login button) falls back to the owner profile
    page, which carries the same nav. A login button on either page
    still fails session-lost; both pages null = fail. Never false-PASS.

    An ambiguous read is also what slow hydration looks like: goto's
    settle can elapse before the nav mounts (09-04 15:10 — 7 reads
    false-FAILED session-lost while the session was authed), so each
    page is re-polled twice before being judged ambiguous.
    """
    state = {}
    for url in ("https://x.com/home",
                f"https://x.com/{OWNER_HANDLE}"):
        cdp.goto(url, settle=4.0)
        state = json.loads(cdp.evaluate(_NAV_EXPR) or "{}")
        for settle in (3.0, 6.0):
            if state.get("loginBtn") or state.get("handle"):
                break  # definitive
            time.sleep(settle)
            state = json.loads(cdp.evaluate(_NAV_EXPR) or "{}")
        if state.get("loginBtn") or state.get("handle"):
            break  # definitive on either page
    handle = (state.get("handle") or "").lstrip("/")
    return {"handle": handle or None,
            "authed": bool(handle),
            "login_btn": bool(state.get("loginBtn"))}


def assert_owner_session(cdp: CdpSession, action: str) -> str:
    """Exit 3 if not logged in as the owner account; return handle."""
    from . import envelope
    state = who_am_i(cdp)
    if state["login_btn"] or not state["authed"]:
        envelope.fail(action, envelope.SESSION, "session-lost",
                      "X session lost or not logged in — owner login needed "
                      "on the agent Chrome (Pi display)",
                      diagnostics=state)
    if state["handle"] != OWNER_HANDLE:
        envelope.fail(action, envelope.SESSION, "wrong-session",
                      f"logged in as @{state['handle']}, expected "
                      f"@{OWNER_HANDLE}", diagnostics=state)
    return state["handle"]


__all__ = ["CdpError", "CdpSession", "cdp_base_url", "cdp_reachable",
           "open_tab", "who_am_i", "assert_owner_session", "OWNER_HANDLE"]
