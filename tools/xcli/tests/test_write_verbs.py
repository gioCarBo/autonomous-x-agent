"""Guard paths of the write verbs (write.py), without a browser.

Each verb is a recipe of gates in front of a trusted click. These tests
drive the verbs against a fake CDP tab that answers canned JSON per probe
and records every command, so we can assert two things the live runs
cannot cheaply prove: the envelope (error code, evidence fields, exit
code) and that nothing was clicked when a guard, an already-done state or
--check stopped the recipe.

Harness: session.open_tab returns the fake, assert_owner_session is a
no-op, failure.report_bug / save_screenshot are recorded no-ops (plus
XCLI_NO_ISSUE=1), caps read a dict instead of memory/state.json, and
items.json registration is stubbed. envelope.emit/fail call sys.exit, so
every run ends in SystemExit and the single stdout line is the envelope.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xcli import session, write  # noqa: E402

OWNER = session.OWNER_HANDLE
THEIR = "quietfern_dev"           # invented, not an account we track
THEIR_URL = f"https://x.com/{THEIR}/status/4242001"
OUR_URL = f"https://x.com/{OWNER}/status/4242002"

POS = json.dumps({"x": 120.0, "y": 340.0})
FOCAL_OK = json.dumps({"nArticles": 3, "focal": True, "reply": True})

# Probe fingerprints: a substring unique to each JS snippet write.py evaluates.
PERMALINK_PROBE = "nArticles"
TOGGLE_STATE = "off: !!focal.querySelector"        # _focal_state_js
FOLLOW_STATE = "find('-follow')"                   # _follow_state_js
CARET_CLICK = '[data-testid="caret"]'              # CARET_JS
RETWEET_CLICK = '[data-testid="retweet"], [data-testid="unretweet"]'  # _open_retweet_menu locator
DELETE_PROBE = "ok: !!del"                         # DELETE_MENU_PROBE_JS
DELETE_CLICK = "del.scrollIntoView"                # DELETE_MENU_CLICK_JS
DELETE_CONFIRM = "/^(elimina|delete)$/i"           # DELETE_CONFIRM_JS
PIN_PROBE = "ok: !!(pin || unpin)"                 # PIN_MENU_PROBE_JS
PIN_CLICK = "pin.scrollIntoView"                   # PIN_MENU_CLICK_JS


def toggle(on: bool, off: bool) -> str:
    return json.dumps({"focal": True, "on": on, "off": off})


def follow_state(follow: bool, unfollow: bool) -> str:
    return json.dumps({"follow": follow, "unfollow": unfollow})


class Clock:
    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t

    def sleep(self, s=0, *a, **k):
        self.t += float(s or 0)


class FakeCdp:
    """Answers evaluate(js) by the first rule whose needle is in js; None
    otherwise (what a locator returns when the element is missing)."""

    def __init__(self, rules):
        self.rules = list(rules)
        self.evals: list[str] = []
        self.commands: list[tuple[str, dict | None]] = []
        self.gotos: list[str] = []
        self.closed = False

    def evaluate(self, js):
        self.evals.append(js)
        for needle, value in self.rules:
            if needle in js:
                return value() if callable(value) else value
        return None

    def command(self, method, params=None, timeout=30):
        self.commands.append((method, params))
        return {}

    def goto(self, url, settle=3.0, max_wait=25.0):
        self.gotos.append(url)

    def close(self):
        self.closed = True

    def evaluated(self, needle: str) -> bool:
        return any(needle in js for js in self.evals)

    def mouse_events(self):
        return [p for m, p in self.commands if m == "Input.dispatchMouseEvent"]

    def key_events(self):
        return [p for m, p in self.commands if m == "Input.dispatchKeyEvent"]


class WriteVerbCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.renders = Path(self.tmp.name) / "renders"
        self.renders.mkdir()
        now = datetime.now().astimezone()
        self.now = now
        self.state = {"caps": {"date": now.date().isoformat()}}
        self.cdp: FakeCdp | None = None
        self.opened: list[tuple[str, str]] = []
        self.bugs: list[dict] = []
        clock = Clock()

        def open_tab(start_url, action="session"):
            self.opened.append((start_url, action))
            if self.cdp is None:
                self.fail(f"{action} opened a tab the test did not expect")
            return self.cdp

        def report_bug(action, signature, error_code, message,
                       diagnostics=None, screenshot=None):
            self.bugs.append({"action": action, "signature": signature,
                              "error_code": error_code})
            return {}

        stack = ExitStack()
        self.addCleanup(stack.close)
        for p in (
            patch.object(write.session, "open_tab", open_tab),
            patch.object(write.session, "assert_owner_session",
                         lambda cdp, action: OWNER),
            patch.object(write.failure, "report_bug", report_bug),
            patch.object(write.failure, "save_screenshot",
                         lambda cdp, signature=None: None),
            patch.object(write.caps, "load", lambda path=None: self.state),
            patch.object(write.caps, "save", lambda state, path=None: None),
            patch.object(write, "_register_item", lambda evidence, tag: True),
            patch.object(write, "_close_item", lambda url: True),
            patch.object(write, "RENDERS", self.renders),
            patch.object(write.time, "sleep", clock.sleep),
            patch.object(write.time, "monotonic", clock.monotonic),
            patch.dict(os.environ, {"XCLI_NO_ISSUE": "1"}),
        ):
            stack.enter_context(p)

    # -- helpers ---------------------------------------------------------
    def caps(self, **counters):
        self.state["caps"].update(counters)

    def tab(self, *rules) -> FakeCdp:
        self.cdp = FakeCdp(rules)
        return self.cdp

    def run_verb(self, fn, *args, **kwargs):
        """Run a verb to its SystemExit; return (exit code, envelope)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), \
             self.assertRaises(SystemExit) as ctx:
            fn(*args, **kwargs)
        lines = out.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 1, f"expected one envelope line, got {lines}")
        return ctx.exception.code, json.loads(lines[0])

    def assert_failed(self, result, error_code, action):
        code, env = result
        self.assertEqual(code, 1)
        self.assertFalse(env["ok"])
        self.assertEqual(env["action"], action)
        self.assertEqual(env["error"]["code"], error_code)
        return env["error"]

    def assert_ok(self, result, action):
        code, env = result
        self.assertEqual(code, 0)
        self.assertTrue(env["ok"])
        self.assertEqual(env["action"], action)
        return env["evidence"]

    def assert_no_tab(self):
        self.assertEqual(self.opened, [])

    def assert_tab_closed(self):
        self.assertEqual(len(self.opened), 1)
        self.assertTrue(self.cdp.closed)


class RequireCap(WriteVerbCase):
    def test_returns_detail_when_allowed(self):
        self.caps(replies=3)
        self.assertEqual(write._require_cap("reply", "reply", THEIR_URL), "replies 4/25")

    def test_fails_cap_reached_with_kind_in_diagnostics(self):
        self.caps(follows=3)
        err = self.assert_failed(self.run_verb(write._require_cap, "follow", "follow", "u"),
                                 "cap-reached", "follow")
        self.assertEqual(err["diagnostics"], {"url": "u", "kind": "follow"})
        self.assertIn("follows 3/3 today", err["message"])
        self.assertEqual(self.bugs, [])  # a cap is not a bug


class Reply(WriteVerbCase):
    def test_bad_url_before_any_tab(self):
        err = self.assert_failed(self.run_verb(write.reply, "https://example.org/p/1", "hi"),
                                 "bad-url", "reply")
        self.assertEqual(err["diagnostics"]["url"], "https://example.org/p/1")
        self.assert_no_tab()

    def test_media_outside_renders_is_media_policy(self):
        shot = Path(self.tmp.name) / "screenshot.png"
        shot.write_bytes(b"\x89PNG")
        err = self.assert_failed(self.run_verb(write.reply, THEIR_URL, "hi", media=[str(shot)]),
                                 "media-policy", "reply")
        self.assertIn("renders/", err["message"])
        self.assert_no_tab()

    def test_cap_reached_before_any_tab(self):
        self.caps(replies=25)
        err = self.assert_failed(self.run_verb(write.reply, THEIR_URL, "hi"),
                                 "cap-reached", "reply")
        self.assertEqual(err["diagnostics"], {"url": THEIR_URL, "kind": "reply"})
        self.assert_no_tab()


class PostAndQuote(WriteVerbCase):
    def two_recent_posts(self):
        self.caps(post_times=[(self.now - timedelta(minutes=m)).isoformat(timespec="minutes")
                              for m in (12, 41)])

    def test_post_cap_reached_on_originals(self):
        self.caps(originals=5)
        err = self.assert_failed(self.run_verb(write.post, "hello"), "cap-reached", "post")
        self.assertIn("originals 5/5 today", err["message"])
        self.assertEqual(err["diagnostics"], {"url": None, "kind": "original"})
        self.assert_no_tab()

    def test_post_two_per_hour_rule(self):
        self.caps(originals=2)
        self.two_recent_posts()
        err = self.assert_failed(self.run_verb(write.post, "hello"), "cap-reached", "post")
        self.assertIn("2 posts in the last hour", err["message"])
        self.assert_no_tab()

    def test_quote_shares_the_original_cap(self):
        self.caps(originals=5)
        err = self.assert_failed(self.run_verb(write.quote, THEIR_URL, "worth a look"),
                                 "cap-reached", "quote")
        self.assertEqual(err["diagnostics"], {"url": THEIR_URL, "kind": "original"})
        self.assert_no_tab()

    def test_quote_two_per_hour_rule(self):
        self.two_recent_posts()
        err = self.assert_failed(self.run_verb(write.quote, THEIR_URL, "worth a look"),
                                 "cap-reached", "quote")
        self.assertIn("2 posts in the last hour", err["message"])
        self.assert_no_tab()

    def test_quote_bad_url(self):
        self.assert_failed(self.run_verb(write.quote, "x.com/nothing", "t"), "bad-url", "quote")
        self.assert_no_tab()


class Like(WriteVerbCase):
    def test_already_liked_exits_ok_without_clicking(self):
        cdp = self.tab((PERMALINK_PROBE, FOCAL_OK), (TOGGLE_STATE, toggle(on=True, off=False)))
        ev = self.assert_ok(self.run_verb(write.like, THEIR_URL), "like")
        self.assertEqual(ev, {"url": THEIR_URL, "already_liked": True})
        self.assertEqual(cdp.mouse_events(), [])
        self.assert_tab_closed()

    def test_check_only_passes_gates_without_clicking(self):
        cdp = self.tab((PERMALINK_PROBE, FOCAL_OK), (TOGGLE_STATE, toggle(on=False, off=True)))
        ev = self.assert_ok(self.run_verb(write.like, THEIR_URL, check_only=True), "like")
        self.assertTrue(ev["checked"])
        self.assertEqual(ev["caps"], "likes 1/30")
        self.assertEqual(ev["stage"], "gates-passed-not-submitted")
        self.assertEqual(cdp.mouse_events(), [])
        self.assertEqual(self.state["caps"]["likes"], 0)  # not consumed
        self.assert_tab_closed()

    def test_cap_reached_after_state_probe_no_click(self):
        self.caps(likes=30)
        cdp = self.tab((PERMALINK_PROBE, FOCAL_OK), (TOGGLE_STATE, toggle(on=False, off=True)))
        err = self.assert_failed(self.run_verb(write.like, THEIR_URL), "cap-reached", "like")
        self.assertEqual(err["diagnostics"]["kind"], "like")
        self.assertEqual(cdp.mouse_events(), [])
        self.assertEqual(self.bugs, [])
        self.assert_tab_closed()

    def test_bad_url(self):
        self.assert_failed(self.run_verb(write.like, "https://x.com/home"), "bad-url", "like")
        self.assert_no_tab()


class Repost(WriteVerbCase):
    def test_already_reposted_exits_ok_without_clicking(self):
        cdp = self.tab((PERMALINK_PROBE, FOCAL_OK), (TOGGLE_STATE, toggle(on=True, off=False)))
        ev = self.assert_ok(self.run_verb(write.repost, THEIR_URL), "repost")
        self.assertEqual(ev, {"url": THEIR_URL, "already_reposted": True})
        self.assertEqual(cdp.mouse_events(), [])
        self.assert_tab_closed()

    def test_cap_reached_before_the_menu_opens(self):
        self.caps(reposts=2)
        cdp = self.tab((PERMALINK_PROBE, FOCAL_OK), (TOGGLE_STATE, toggle(on=False, off=True)))
        err = self.assert_failed(self.run_verb(write.repost, THEIR_URL), "cap-reached", "repost")
        self.assertIn("reposts 2/2 today", err["message"])
        self.assertEqual(cdp.mouse_events(), [])
        self.assertFalse(cdp.evaluated(RETWEET_CLICK))
        self.assert_tab_closed()


class Follow(WriteVerbCase):
    def test_bad_handle(self):
        err = self.assert_failed(self.run_verb(write.follow, "@not a handle", "follow-back"),
                                 "bad-handle", "follow")
        self.assertIn("not a handle", err["message"])
        self.assert_no_tab()

    def test_reason_required(self):
        self.assert_failed(self.run_verb(write.follow, THEIR, "   "), "reason-required", "follow")
        self.assert_no_tab()

    def test_already_following_exits_ok_without_clicking(self):
        cdp = self.tab((FOLLOW_STATE, follow_state(follow=False, unfollow=True)))
        ev = self.assert_ok(self.run_verb(write.follow, "@" + THEIR, "follow-back"), "follow")
        self.assertEqual(ev, {"handle": THEIR, "already_following": True})
        self.assertEqual(cdp.mouse_events(), [])
        self.assertEqual(cdp.gotos, [f"https://x.com/{THEIR}"])
        self.assert_tab_closed()

    def test_check_only_passes_gates_without_clicking(self):
        cdp = self.tab((FOLLOW_STATE, follow_state(follow=True, unfollow=False)))
        ev = self.assert_ok(self.run_verb(write.follow, THEIR, "replied to us", check_only=True),
                            "follow")
        self.assertTrue(ev["checked"])
        self.assertEqual((ev["handle"], ev["reason"], ev["caps"]),
                         (THEIR, "replied to us", "follows 1/3"))
        self.assertEqual(cdp.mouse_events(), [])
        self.assertEqual(self.state["caps"]["follows"], 0)
        self.assert_tab_closed()

    def test_cap_reached_no_click(self):
        self.caps(follows=3)
        cdp = self.tab((FOLLOW_STATE, follow_state(follow=True, unfollow=False)))
        err = self.assert_failed(self.run_verb(write.follow, THEIR, "follow-back"),
                                 "cap-reached", "follow")
        self.assertEqual(err["diagnostics"], {"url": f"https://x.com/{THEIR}", "kind": "follow"})
        self.assertEqual(cdp.mouse_events(), [])
        self.assert_tab_closed()


DELETE_MENU = ["Elimina", "Fissa sul profilo", "Modifica chi può rispondere"]
NO_DELETE_MENU = ["Fissa sul profilo", "Modifica chi può rispondere"]


class Delete(WriteVerbCase):
    def test_bad_url(self):
        self.assert_failed(self.run_verb(write.delete, "not-a-url"), "bad-url", "delete")
        self.assert_no_tab()

    def test_foreign_handle_is_not_ours_before_any_tab(self):
        err = self.assert_failed(self.run_verb(write.delete, THEIR_URL), "not-ours", "delete")
        self.assertIn("@" + THEIR, err["message"])
        self.assertEqual(err["diagnostics"], {"url": THEIR_URL})
        self.assert_no_tab()

    def test_check_only_opens_menu_then_escapes_without_confirming(self):
        cdp = self.tab(
            (PERMALINK_PROBE, FOCAL_OK),
            (CARET_CLICK, POS),
            (DELETE_PROBE, json.dumps({"ok": True, "n": 3, "labels": DELETE_MENU})),
        )
        ev = self.assert_ok(self.run_verb(write.delete, OUR_URL, check_only=True), "delete")
        self.assertTrue(ev["checked"])
        self.assertEqual(ev["stage"], "delete-item-visible-not-submitted")
        self.assertEqual(ev["labels"], DELETE_MENU)
        # the only click is the caret (press + release); the menu item and
        # the confirm sheet are never located, let alone clicked
        self.assertEqual([m["type"] for m in cdp.mouse_events()],
                         ["mousePressed", "mouseReleased"])
        self.assertFalse(cdp.evaluated(DELETE_CLICK))
        self.assertFalse(cdp.evaluated(DELETE_CONFIRM))
        self.assertEqual([k["key"] for k in cdp.key_events()], ["Escape", "Escape"])
        self.assertEqual(self.bugs, [])
        self.assert_tab_closed()

    def test_menu_without_delete_item_fails_named_stage(self):
        cdp = self.tab(
            (PERMALINK_PROBE, FOCAL_OK),
            (CARET_CLICK, POS),
            (DELETE_PROBE, json.dumps({"ok": False, "n": 2, "labels": NO_DELETE_MENU})),
        )
        err = self.assert_failed(self.run_verb(write.delete, OUR_URL), "no-delete-item", "delete")
        self.assertEqual(err["signature"], "delete:no-delete-item")
        self.assertIn("Fissa sul profilo", err["message"])
        self.assertEqual(err["diagnostics"], {"url": OUR_URL})
        self.assertEqual(self.bugs, [{"action": "delete", "signature": "delete:no-delete-item",
                                      "error_code": "no-delete-item"}])
        self.assertEqual(len(cdp.mouse_events()), 2)  # caret only
        self.assertFalse(cdp.evaluated(DELETE_CLICK))
        self.assertFalse(cdp.evaluated(DELETE_CONFIRM))
        self.assertEqual([k["key"] for k in cdp.key_events()], ["Escape", "Escape"])
        self.assert_tab_closed()


class Pin(WriteVerbCase):
    def test_foreign_handle_is_not_ours_before_any_tab(self):
        err = self.assert_failed(self.run_verb(write.pin, THEIR_URL), "not-ours", "pin")
        self.assertIn("@" + THEIR, err["message"])
        self.assert_no_tab()

    def test_bad_url(self):
        self.assert_failed(self.run_verb(write.pin, "https://x.com/" + OWNER), "bad-url", "pin")
        self.assert_no_tab()

    def test_already_pinned_exits_ok_without_pinning(self):
        labels = ["Elimina", "Non fissare sul profilo"]
        cdp = self.tab(
            (PERMALINK_PROBE, FOCAL_OK),
            (CARET_CLICK, POS),
            (PIN_PROBE, json.dumps({"ok": True, "already": True, "n": 2, "labels": labels})),
        )
        ev = self.assert_ok(self.run_verb(write.pin, OUR_URL), "pin")
        self.assertEqual(ev, {"url": OUR_URL, "already_pinned": True})
        self.assertEqual(len(cdp.mouse_events()), 2)  # caret only
        self.assertFalse(cdp.evaluated(PIN_CLICK))
        self.assertFalse(cdp.evaluated("confirmationSheetConfirm"))
        self.assert_tab_closed()

    def test_check_only_reports_labels_without_pinning(self):
        labels = ["Elimina", "Fissa sul profilo"]
        cdp = self.tab(
            (PERMALINK_PROBE, FOCAL_OK),
            (CARET_CLICK, POS),
            (PIN_PROBE, json.dumps({"ok": True, "already": False, "n": 2, "labels": labels})),
        )
        ev = self.assert_ok(self.run_verb(write.pin, OUR_URL, check_only=True), "pin")
        self.assertEqual((ev["checked"], ev["stage"], ev["labels"]),
                         (True, "pin-item-visible-not-submitted", labels))
        self.assertEqual(len(cdp.mouse_events()), 2)  # caret only
        self.assertFalse(cdp.evaluated(PIN_CLICK))
        self.assert_tab_closed()


if __name__ == "__main__":
    unittest.main()
