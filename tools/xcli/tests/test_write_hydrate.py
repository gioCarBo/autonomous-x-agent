"""Regression tests for issue #15 (permalink empty-shell vs no-reply-button).

The 2026-09-05 14:14 screenshot shows a loaded X chrome (nav + logged-in
account) with the permalink still spinning — no <article>, so the reply
button locator returned null. _click_center used to fail on that first
null and file no-reply-button, which the agent then misread as a thread
restriction.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xcli import write  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t

    def sleep(self, s=0, *a, **k):
        self.t += float(s or 0)


class FakeCdp:
    def __init__(self, value):
        self.value = value
        self.commands = []
        self.gotos = []
        self.n_eval = 0

    def evaluate(self, js):
        self.n_eval += 1
        v = self.value
        return v() if callable(v) else v

    def goto(self, url, settle=3.0, max_wait=25.0):
        self.gotos.append(url)

    def command(self, method, params=None, timeout=30):
        self.commands.append((method, params))
        return {}


def _fail_gate(action, target_url, gates, text, cdp=None):
    raise RuntimeError(gates.get("stage"))


EMPTY = json.dumps({"nArticles": 0, "focal": False, "reply": False})
FOCAL_NO_REPLY = json.dumps({"nArticles": 1, "focal": True, "reply": False})
FOCAL_READY = json.dumps({"nArticles": 1, "focal": True, "reply": True})
POS = json.dumps({"x": 10.0, "y": 20.0})


class ClickCenterHydrate(unittest.TestCase):
    def test_first_null_then_stable_rect_clicks(self):
        queue = [None, POS, POS]
        cdp = FakeCdp(lambda: queue.pop(0) if queue else None)
        clock = Clock()
        with patch.object(write, "_fail_gate", _fail_gate), \
             patch.object(write.time, "sleep", clock.sleep), \
             patch.object(write.time, "monotonic", clock.monotonic):
            write._click_center(
                cdp, "js", "reply", "no-reply-button",
                "https://x.com/a/status/1", cdp)
        kinds = [c[0] for c in cdp.commands]
        self.assertEqual(kinds, ["Input.dispatchMouseEvent",
                                 "Input.dispatchMouseEvent"])

    def test_never_appears_fails_named_stage(self):
        cdp = FakeCdp(None)
        clock = Clock()
        with patch.object(write, "_fail_gate", _fail_gate), \
             patch.object(write.time, "sleep", clock.sleep), \
             patch.object(write.time, "monotonic", clock.monotonic), \
             self.assertRaises(RuntimeError) as ctx:
            write._click_center(
                cdp, "js", "reply", "no-reply-button",
                "https://x.com/a/status/1", cdp)
        self.assertEqual(str(ctx.exception), "no-reply-button")
        self.assertGreater(cdp.n_eval, 1)


class PermalHydrate(unittest.TestCase):
    def test_reload_once_when_empty_then_focal(self):
        cdp = FakeCdp(None)
        cdp.value = lambda: FOCAL_READY if cdp.gotos else EMPTY
        clock = Clock()
        with patch.object(write.time, "sleep", clock.sleep), \
             patch.object(write.time, "monotonic", clock.monotonic):
            state = write._hydrate_permalink(
                cdp, "https://x.com/[account-10]/status/1", "1")
        self.assertEqual(cdp.gotos, ["https://x.com/[account-10]/status/1"])
        self.assertTrue(state.get("focal"))
        self.assertTrue(state.get("reply"))

    def test_empty_shell_stage_when_reload_also_blank(self):
        cdp = FakeCdp(EMPTY)
        clock = Clock()
        with patch.object(write, "_fail_gate", _fail_gate), \
             patch.object(write.time, "sleep", clock.sleep), \
             patch.object(write.time, "monotonic", clock.monotonic), \
             self.assertRaises(RuntimeError) as ctx:
            write._fail_if_permalink_unusable(
                cdp, "https://x.com/a/status/1", "1", "reply")
        self.assertEqual(str(ctx.exception), "empty-shell")
        self.assertEqual(cdp.gotos, ["https://x.com/a/status/1"])

    def test_focal_without_reply_is_no_reply_button_not_empty_shell(self):
        cdp = FakeCdp(FOCAL_NO_REPLY)
        clock = Clock()
        with patch.object(write, "_fail_gate", _fail_gate), \
             patch.object(write.time, "sleep", clock.sleep), \
             patch.object(write.time, "monotonic", clock.monotonic), \
             self.assertRaises(RuntimeError) as ctx:
            write._fail_if_permalink_unusable(
                cdp, "https://x.com/a/status/1", "1", "reply")
        self.assertEqual(str(ctx.exception), "no-reply-button")
        self.assertEqual(cdp.gotos, [])


if __name__ == "__main__":
    unittest.main()
