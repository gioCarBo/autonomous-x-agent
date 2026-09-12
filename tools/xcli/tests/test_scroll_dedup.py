"""Regression tests: rows without a URL were collected once per scroll round.

_scroll_collect dedups on url_key, and fell back to a positional key when a
row had none — a key that changed with the scroll round, so the virtualized
list re-serving the same row minted a new key every time. The notifications
feed is where it bit: 18 of the 20 rows on 09-05 22:00 had no post_url, and
that envelope reported n=20 carrying 18 distinct notifications. The --limit
cap made it cost real slots rather than just noise.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xcli import read  # noqa: E402


class ReplayCdp:
    """A virtualized list: every round re-serves the rows it served before,
    then appends what scrolling revealed. That repetition is the point."""

    def __init__(self, pages: list[list[dict]]):
        self.pages = pages
        self.round = 0

    def evaluate(self, js):
        if js.startswith("window.scrollBy"):
            return None
        served: list[dict] = []
        for page in self.pages[:self.round + 1]:
            served.extend(page)
        self.round += 1
        return served


def _collect(pages, **kw):
    with patch.object(read.time, "sleep", lambda *a, **k: None):
        return read._scroll_collect(ReplayCdp(pages), "JSON.parse(x).items",
                                    rounds=len(pages), pause=0,
                                    url_key="post_url", **kw)


# The two rows that came back twice on 09-05 22:00, verbatim in shape.
FOLLOW_ROWS = [
    {"actors": ["/GCBullGlasses"], "text": None,
     "time": "2026-09-05T16:49:32.261Z", "post_url": None},
    {"actors": [], "text": None,
     "time": "2026-09-05T16:49:23.980Z", "post_url": None},
]


class UrllessRows(unittest.TestCase):
    def test_a_re_served_row_is_collected_once(self):
        items = _collect([FOLLOW_ROWS, [], []])
        self.assertEqual(len(items), 2)

    def test_the_production_feed_shape_stops_over_reporting(self):
        engaged = {"actors": ["/tomas_hk"], "text": "That math works when...",
                   "time": "2026-09-02T22:41:29.012Z", "post_url": None}
        items = _collect([FOLLOW_ROWS, [engaged], []])
        self.assertEqual(len(items), 3)          # was 5: 2 + 2 again + 1
        self.assertEqual(len(items), len({str(i) for i in items}))

    def test_rows_differing_only_in_content_all_survive(self):
        rows = [{"actors": ["/a"], "text": t, "time": "T", "post_url": None}
                for t in ("first", "second", "third")]
        self.assertEqual(len(_collect([rows, []])), 3)


class UrlRows(unittest.TestCase):
    def test_url_still_wins_over_content(self):
        """X re-renders counts between rounds; the URL is the identity."""
        a = {"post_url": "https://x.com/a/status/1", "text": "12 likes"}
        b = {"post_url": "https://x.com/a/status/1", "text": "13 likes"}
        self.assertEqual(len(_collect([[a], [b]])), 1)

    def test_distinct_urls_both_kept(self):
        a = {"post_url": "https://x.com/a/status/1", "text": "x"}
        b = {"post_url": "https://x.com/a/status/2", "text": "x"}
        self.assertEqual(len(_collect([[a], [b]])), 2)


class LimitInteraction(unittest.TestCase):
    def test_duplicates_no_longer_eat_capped_slots(self):
        pages = [FOLLOW_ROWS,
                 [{"actors": ["/x"], "text": f"n{i}", "time": f"T{i}",
                   "post_url": None} for i in range(3)],
                 []]
        items = _collect(pages, limit=4)
        self.assertEqual(len(items), 4)
        self.assertEqual(len(items), len({str(i) for i in items}))


if __name__ == "__main__":
    unittest.main()
