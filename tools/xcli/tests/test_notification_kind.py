"""`x notifications` rows carry a `kind`.

09-06 09:02 the precheck launched a wake for a notification whose `text` was
our own week-old reply: X embeds the liked post's text in a like cell. The
envelope had no kind, so the wake spent its cycle proving a like was a like.
The extractor now returns the cell's header line and whether the cell is a
tweet; `notification_kind` turns that into like/follow/repost/reply/other.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xcli import read  # noqa: E402


class Kind(unittest.TestCase):
    def test_header_wins_in_italian_and_english(self):
        self.assertEqual(read.notification_kind({"header": "A AhaOtter piace il tuo post", "text": "…"}), "like")
        self.assertEqual(read.notification_kind({"header": "AhaOtter liked your post"}), "like")
        self.assertEqual(read.notification_kind({"header": "itsnex1s ha iniziato a seguirti"}), "follow")
        self.assertEqual(read.notification_kind({"header": "New follower: itsnex1s"}), "follow")
        self.assertEqual(read.notification_kind({"header": "[account-1] ha ripubblicato il tuo post"}), "repost")
        self.assertEqual(read.notification_kind({"header": "[account-2] reposted your post"}), "repost")

    def test_tweet_cells_are_replies_and_the_rest_is_other(self):
        self.assertEqual(read.notification_kind({"header": None, "is_tweet": True, "post_url": "https://x.com/a/status/1"}), "reply")
        self.assertEqual(read.notification_kind({"header": None, "post_url": "https://x.com/a/status/1"}), "reply")
        self.assertEqual(read.notification_kind({"header": "Novità da X", "is_tweet": False}), "other")
        self.assertEqual(read.notification_kind({}), "other")


class FakeCdp:
    def __init__(self, rows):
        self.rows = rows

    def evaluate(self, js):
        return None if js.startswith("window.scrollBy") else list(self.rows)

    def goto(self, url, settle=3.0, max_wait=25.0):
        pass


class Envelope(unittest.TestCase):
    def test_every_row_gets_a_kind(self):
        rows = [{"actors": ["/Heyotter666"], "text": "our old reply", "time": "t", "post_url": None,
                 "header": "A AhaOtter piace il tuo post", "is_tweet": False},
                {"actors": ["/[account-4]"], "text": "answer", "time": "t", "post_url": "https://x.com/f/status/2",
                 "header": None, "is_tweet": True}]
        seen: dict = {}
        with patch.object(read.session, "assert_owner_session", lambda *a, **k: "GCBullGlasses"), \
             patch.object(read.envelope, "emit", lambda action, ev: seen.update(ev)), \
             patch.object(read.time, "sleep", lambda *a, **k: None):
            read.notifications(cdp=FakeCdp(rows), limit=5)
        self.assertEqual([r["kind"] for r in seen["items"]], ["like", "reply"])


if __name__ == "__main__":
    unittest.main()
