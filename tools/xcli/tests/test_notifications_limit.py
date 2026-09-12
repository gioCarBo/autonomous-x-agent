"""Regression tests: `x notifications --limit N` was parsed and thrown away.

cli.py declared --limit (default 20), but read.notifications() took no such
parameter and was called bare, so a run returned whatever three scroll rounds
happened to collect. An agent asking for a wider window silently got the same
feed, and the declared default of 20 was never a cap at all.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xcli import cli, read  # noqa: E402


class FakeCdp:
    """Serves one fresh page of rows per extract call; counts the scrolls."""

    def __init__(self, per_round: int = 5):
        self.per_round = per_round
        self.rounds = 0
        self.scrolls = 0

    def evaluate(self, js):
        if js.startswith("window.scrollBy"):
            self.scrolls += 1
            return None
        start = self.rounds * self.per_round
        self.rounds += 1
        return [{"post_url": f"https://x.com/a/status/{i}"}
                for i in range(start, start + self.per_round)]

    def goto(self, url, settle=3.0, max_wait=25.0):
        pass


def _no_sleep(*a, **k):
    return None


class ScrollCollectLimit(unittest.TestCase):
    def test_limit_truncates_and_stops_scrolling_early(self):
        cdp = FakeCdp(per_round=5)
        with patch.object(read.time, "sleep", _no_sleep):
            items = read._scroll_collect(cdp, "JSON.parse(x).items", rounds=6,
                                         pause=0, url_key="post_url", limit=7)
        self.assertEqual(len(items), 7)
        self.assertEqual(cdp.rounds, 2)   # 5, then 10 >= 7 — no third pass
        self.assertEqual(cdp.scrolls, 1)  # and no scroll after the last batch

    def test_without_limit_every_round_still_runs(self):
        cdp = FakeCdp(per_round=5)
        with patch.object(read.time, "sleep", _no_sleep):
            items = read._scroll_collect(cdp, "JSON.parse(x).items", rounds=3,
                                         pause=0, url_key="post_url")
        self.assertEqual(len(items), 15)
        self.assertEqual(cdp.scrolls, 3)


class NotificationsLimit(unittest.TestCase):
    def _evidence(self, **kw) -> dict:
        seen: dict = {}
        with patch.object(read.session, "assert_owner_session",
                          lambda *a, **k: "GCBullGlasses"), \
             patch.object(read.envelope, "emit",
                          lambda action, ev: seen.update(ev)), \
             patch.object(read.time, "sleep", _no_sleep):
            read.notifications(cdp=FakeCdp(per_round=20), **kw)
        return seen

    def test_limit_caps_the_envelope(self):
        ev = self._evidence(limit=3)
        self.assertEqual(ev["n"], 3)
        self.assertEqual(len(ev["items"]), 3)

    def test_default_is_the_declared_twenty(self):
        self.assertEqual(self._evidence()["n"], 20)


class LimitFlag(unittest.TestCase):
    def test_flag_reaches_the_verb(self):
        with patch.object(cli.read, "notifications") as verb:
            cli.main(["notifications", "--limit", "5"])
        verb.assert_called_once_with(limit=5)

    def test_default_reaches_the_verb(self):
        with patch.object(cli.read, "notifications") as verb:
            cli.main(["notifications"])
        verb.assert_called_once_with(limit=20)

    def test_zero_and_negative_are_refused(self):
        for bad in ("0", "-3"):
            with patch.object(cli.read, "notifications") as verb, \
                 patch("sys.stderr"), self.assertRaises(SystemExit) as ctx:
                cli.main(["notifications", "--limit", bad])
            self.assertEqual(ctx.exception.code, 2)  # argparse usage error
            verb.assert_not_called()


if __name__ == "__main__":
    unittest.main()
