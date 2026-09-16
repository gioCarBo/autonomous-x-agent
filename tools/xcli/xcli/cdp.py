"""CDP session over a dedicated tab: evaluate JS, navigate, screenshot.

One CdpSession = one Chrome tab owned end-to-end by this invocation. The tab
is created on entry and closed on exit — tab accumulation becomes
structurally impossible.
"""

import base64
import json
import time
import urllib.error
import urllib.request

from .ws import WsClient, WsError


class CdpError(Exception):
    pass


class CdpSession:
    def __init__(self, base_url: str, start_url: str = "about:blank"):
        self.base = base_url.rstrip("/")
        self.tab_id = None
        self.ws = None
        self._msg_id = 0
        self._open(start_url)

    # -- lifecycle ----------------------------------------------------------

    def _open(self, start_url: str) -> None:
        tab = self._http("PUT" if start_url else "GET",
                         f"/json/new?{start_url}" if start_url else "/json/new")
        if not tab or "id" not in tab:
            raise CdpError(f"could not create tab: {tab}")
        self.tab_id = tab["id"]
        ws_url = tab.get("webSocketDebuggerUrl")
        if not ws_url:
            raise CdpError(f"no webSocketDebuggerUrl for tab {self.tab_id}")
        rest = ws_url.split("://", 1)[1]
        host, path = rest.split("/", 1)
        hostport, _, hostpath = host.partition("/")
        if ":" in hostport:
            h, p = hostport.rsplit(":", 1)
        else:
            h, p = hostport, "80"
        path = "/" + path if not hostpath else "/" + hostpath + "/" + path
        self.ws = WsClient(h, int(p), path)

    def close(self) -> None:
        """Best-effort teardown: never mask the verb's real outcome."""
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None
        if self.tab_id:
            try:
                self._http("GET", f"/json/close/{self.tab_id}")
            except Exception:
                pass
            self.tab_id = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- transport ----------------------------------------------------------

    def _http(self, method: str, path: str) -> dict:
        req = urllib.request.Request(self.base + path, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                body = r.read().decode()
        except (urllib.error.URLError, OSError) as e:
            raise CdpError(f"CDP endpoint unreachable ({self.base}{path}): {e}")
        if not body.strip():
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"raw": body}  # e.g. /json/close says "Target is closing"

    def command(self, method: str, params: dict | None = None,
                timeout: float = 30.0) -> dict:
        self._msg_id += 1
        mid = self._msg_id
        self.ws.send_text(json.dumps({"id": mid, "method": method,
                                      "params": params or {}}))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                msg = json.loads(self.ws.recv_message())
            except (WsError, OSError, json.JSONDecodeError) as e:
                raise CdpError(f"CDP transport error on {method}: {e}")
            if msg.get("id") != mid:
                continue  # unsolicited event
            if "error" in msg:
                raise CdpError(f"CDP error on {method}: {msg['error']}")
            return msg.get("result", {})
        raise CdpError(f"timeout waiting for {method} response")

    # -- page operations ------------------------------------------------------

    def evaluate(self, expression: str, timeout: float = 30.0):
        """Evaluate JS, return the JSON value. Raises CdpError on JS exception."""
        res = self.command("Runtime.evaluate",
                           {"expression": expression, "returnByValue": True,
                            "awaitPromise": True}, timeout=timeout)
        r = res.get("result", {})
        if r.get("subtype") == "error" or "exceptionDetails" in res:
            detail = json.dumps(res.get("exceptionDetails", r))[:400]
            raise CdpError(f"JS evaluation failed: {detail}")
        return r.get("value")

    def goto(self, url: str, settle: float = 3.0, max_wait: float = 25.0) -> None:
        self.command("Page.navigate", {"url": url})
        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            try:
                state = self.evaluate("document.readyState", timeout=10)
            except CdpError:
                state = None
            if state == "complete":
                break
            time.sleep(0.5)
        time.sleep(settle)  # X renders after readyState complete

    def screenshot_png(self) -> bytes:
        res = self.command("Page.captureScreenshot", {"format": "png"},
                           timeout=15)
        return base64.b64decode(res["data"])
