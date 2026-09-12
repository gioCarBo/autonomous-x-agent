"""`x sweep` and multi-URL `x status`: the observation sweep and the own-post
readout as one verb each, instead of one tab + one LLM turn per target.
Sessions on 09-05 spent 5-16 `x profile` calls (20 x 280-char items each)
and 4-11 `x status` calls per wake on exactly this."""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xcli import read  # noqa: E402
from xcli.cdp import CdpError  # noqa: E402

NOW = 1_800_000_000_000  # fixed "now" in ms


def sid(age_min: int) -> str:
    """A snowflake ID for a post created `age_min` minutes before NOW."""
    return str((NOW - age_min * 60_000 - read.TWITTER_EPOCH_MS) << 22)


def item(handle: str, age_min: int, text: str = "t") -> dict:
    return {"url": f"https://x.com/{handle}/status/{sid(age_min)}",
            "time": "2026-09-05T00:00:00.000Z", "text": text * 280}


class ProfileCdp:
    """Serves a profile per handle; one handle can be made to blow up."""

    def __init__(self, timelines: dict, broken: set = ()):
        self.timelines, self.broken, self.handle, self.gotos = timelines, set(broken), None, []

    def goto(self, url, settle=3.0, max_wait=25.0):
        self.handle = url.rstrip("/").split("/")[-1]
        self.gotos.append(self.handle)
        if self.handle in self.broken:
            raise CdpError("tab wedged")

    def evaluate(self, js, timeout=30.0):
        if js.startswith("window."):
            return None
        items = self.timelines.get(self.handle, [])
        if "JSON.parse" in js:
            return items
        return json.dumps({"handle": self.handle, "name": self.handle, "bio": "",
                           "counts": {"following": "827", "verified_followers": "725.315"},
                           "timeline_rendered": bool(items), "items": items})


def run_sweep(cdp, handles, **kw) -> dict:
    seen = {}
    with patch.object(read.session, "assert_owner_session", lambda *a, **k: "GCBullGlasses"), \
         patch.object(read.envelope, "emit", lambda action, ev: seen.update(ev)), \
         patch.object(read.time, "sleep", lambda *a, **k: None):
        read.sweep(handles, cdp=cdp, now_ms=NOW, pace=0, **kw)
    return seen


class Snowflake(unittest.TestCase):
    def test_decode_roundtrip(self):
        self.assertEqual(read.snowflake_ms(sid(42)), NOW - 42 * 60_000)

    def test_garbage_is_none(self):
        self.assertIsNone(read.snowflake_ms(None))
        self.assertIsNone(read.snowflake_ms("abc"))


class Sweep(unittest.TestCase):
    def test_only_fresh_items_survive_and_are_trimmed(self):
        cdp = ProfileCdp({"a": [item("a", 5000), item("a", 170), item("a", 12)],
                          "b": [item("b", 600)]})
        ev = run_sweep(cdp, ["a", "b"], since_min=180)
        self.assertEqual(ev["n_fresh"], 2)
        a = next(h for h in ev["handles"] if h["handle"] == "a")
        self.assertEqual([f["age_min"] for f in a["fresh"]], [12, 170])  # youngest first
        self.assertEqual(len(a["fresh"][0]["text"]), 80)                # 280 -> 80 chars
        b = next(h for h in ev["handles"] if h["handle"] == "b")
        self.assertEqual(b["fresh"], [])
        self.assertTrue(b["timeline_rendered"])

    def test_one_broken_handle_does_not_sink_the_sweep(self):
        cdp = ProfileCdp({"a": [item("a", 10)], "c": [item("c", 20)]}, broken={"b"})
        ev = run_sweep(cdp, ["a", "b", "c"])
        self.assertEqual([h["handle"] for h in ev["handles"]], ["a", "c"])
        self.assertEqual(ev["errors"][0]["handle"], "b")
        self.assertIn("tab wedged", ev["errors"][0]["error"])
        self.assertEqual(cdp.gotos, ["a", "b", "c"])  # kept going

    def test_unrendered_timeline_is_reported_not_hidden(self):
        ev = run_sweep(ProfileCdp({"a": []}), ["a"])
        self.assertFalse(ev["handles"][0]["timeline_rendered"])
        self.assertEqual(ev["handles"][0]["fresh"], [])

    def test_followers_is_filled_from_verified_followers(self):
        """X's header links the count as /verified_followers now; the agent
        reads counts.followers and saw None for days ("counts stub")."""
        ev = run_sweep(ProfileCdp({"a": [item("a", 3)]}), ["a"])
        self.assertEqual(ev["handles"][0]["counts"]["followers"], "725.315")
        self.assertEqual(ev["handles"][0]["counts"]["verified_followers"], "725.315")

    def test_items_without_a_status_id_are_skipped(self):
        cdp = ProfileCdp({"a": [{"url": "https://x.com/a", "time": None, "text": "x"}, item("a", 3)]})
        self.assertEqual(run_sweep(cdp, ["a"])["n_fresh"], 1)


class StatusCdp:
    def __init__(self, posts: dict):
        self.posts, self.url = posts, None

    def goto(self, url, settle=3.0, max_wait=25.0):
        self.url = url

    def evaluate(self, js, timeout=30.0):
        d = self.posts.get(self.url)
        return json.dumps(d) if d else None


def run_status(cdp, urls) -> dict:
    seen = {}
    with patch.object(read.session, "assert_owner_session", lambda *a, **k: "GCBullGlasses"), \
         patch.object(read.envelope, "emit", lambda action, ev: seen.update(ev)), \
         patch.object(read.time, "sleep", lambda *a, **k: None):
        read.status(urls, cdp=cdp)
    return seen


class MultiStatus(unittest.TestCase):
    U1, U2, U3 = ("https://x.com/a/status/1", "https://x.com/a/status/2", "https://x.com/a/status/3")

    def test_single_url_keeps_the_flat_envelope(self):
        ev = run_status(StatusCdp({self.U1: {"url": self.U1, "text": "hi", "metrics": {"likes": "1,2K", "views": "7"}}}), self.U1)
        self.assertEqual(ev["text"], "hi")
        self.assertEqual(ev["metrics"]["likes"], 1200)
        self.assertNotIn("items", ev)

    def test_many_urls_share_the_tab_and_return_items(self):
        cdp = StatusCdp({self.U1: {"url": self.U1, "text": "one", "metrics": {"views": "10"}},
                         self.U3: {"url": self.U3, "text": "three", "metrics": {"views": "30"}}})
        ev = run_status(cdp, [self.U1, self.U2, self.U3])
        self.assertEqual(ev["n"], 3)
        self.assertEqual([i.get("text") for i in ev["items"]], ["one", None, "three"])
        self.assertEqual(ev["items"][1], {"requested_url": self.U2, "error": "article-not-found"})
        self.assertEqual(ev["items"][0]["metrics"]["views"], 10)


if __name__ == "__main__":
    unittest.main()
