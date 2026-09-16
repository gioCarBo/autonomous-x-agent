"""stats.py: the wake reads a summary, never the file; record is an upsert."""
from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import stats  # noqa: E402

U1, U2 = "https://x.com/GCBullGlasses/status/1", "https://x.com/GCBullGlasses/status/2"
NOW = datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc)


def env(*items):
    """An `x status` envelope, flat for one item, items[] for several."""
    ev = items[0] if len(items) == 1 else {"n": len(items), "items": list(items)}
    return json.dumps({"ok": True, "action": "status", "evidence": ev})


def post(url, text, views, likes=0):
    return {"url": url, "text": text, "metrics": {"views": views, "likes": likes, "reposts": 0, "replies": 0}}


class Record(unittest.TestCase):
    def setUp(self):
        self.data = {"daily": [{"date": "2026-09-05", "followers": 79, "following": 61, "posts_total": 56,
                                "excluded": [], "recent_posts": [
                                    {"text": "old row without url", "views": 10, "likes": 1, "reposts": 0,
                                     "replies": 0, "posted_at": "2026-09-05", "kind": "reply", "author": "agent"}],
                                "totals": {"views": 10, "likes": 1, "reposts": 0, "replies": 0},
                                "engagement_rate": 0.1}]}

    def rec(self, raw, **kw):
        return stats.record(self.data, stats._envelope_items(raw), today="2026-09-06",
                            now_iso="2026-09-06T08:00+02:00", **kw)

    def test_new_day_inherits_the_window_and_updates_by_text(self):
        rep = self.rec(env(post(U1, "old row without url", 42, 3)), followers=80)
        self.assertEqual(rep, {"date": "2026-09-06", "followers": 80, "posts": 1, "updated": 1, "added": 0, "skipped": 0})
        day = self.data["daily"][0]
        self.assertEqual(day["date"], "2026-09-06")
        self.assertEqual(self.data["daily"][1]["date"], "2026-09-05")          # history kept
        self.assertEqual(day["recent_posts"][0]["views"], 42)
        self.assertEqual(day["recent_posts"][0]["url"], U1)                      # url backfilled
        self.assertEqual(self.data["daily"][1]["recent_posts"][0]["views"], 10)  # yesterday untouched
        self.assertEqual(day["totals"], {"views": 42, "likes": 3, "reposts": 0, "replies": 0})
        self.assertEqual(day["engagement_rate"], round(3 / 42, 4))

    def test_same_day_is_an_upsert_not_a_duplicate(self):
        self.rec(env(post(U2, "brand new", 5)), kind="original")
        self.rec(env(post(U2, "brand new", 9)))
        day = self.data["daily"][0]
        self.assertEqual(len(self.data["daily"]), 2)
        new = [p for p in day["recent_posts"] if p.get("url") == U2]
        self.assertEqual(len(new), 1)
        self.assertEqual((new[0]["views"], new[0]["kind"], new[0]["posted_at"]), (9, "original", "2026-09-06"))

    def test_error_rows_are_skipped_and_counted(self):
        rep = self.rec(env(post(U1, "old row without url", 11), {"requested_url": U2, "error": "article-not-found"}))
        self.assertEqual((rep["updated"], rep["skipped"]), (1, 1))

    def test_zero_views_gives_null_rate_not_zero(self):
        self.data["daily"][0]["recent_posts"] = []
        self.rec(env(post(U1, "x", 0)))
        self.assertIsNone(self.data["daily"][0]["engagement_rate"])

    def test_known_kinds_label_new_rows_and_repair_mislabeled_ones(self):
        self.rec(env(post(U1, "old row without url", 42)), known_kinds={U1: "original"})
        self.assertEqual(self.data["daily"][0]["recent_posts"][0]["kind"], "original")  # repaired on merge
        self.rec(env(post(U2, "fresh take", 5)), known_kinds={U2: "original"})
        new = [p for p in self.data["daily"][0]["recent_posts"] if p.get("url") == U2][0]
        self.assertEqual(new["kind"], "original")  # labeled on add

    def test_items_kinds_reads_the_tracker(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "items.json")
            open(f, "w").write(json.dumps({"items": [{"url": U1, "kind": "original"}, {"url": None, "kind": "reply"}]}))
            self.assertEqual(stats._items_kinds(Path(f)), {U1: "original"})
            self.assertEqual(stats._items_kinds(Path(os.path.join(d, "missing.json"))), {})
            open(f, "w").write("not json")
            self.assertEqual(stats._items_kinds(Path(f)), {})


class Summary(unittest.TestCase):
    def test_is_short_and_carries_the_kpis(self):
        data = {"daily": [
            {"date": "2026-09-06", "followers": 81, "following": 61, "posts_total": 58, "measured_at": "2026-09-06T07:30+00:00",
             "recent_posts": [{"url": U1, "text": "big one\nsecond line", "views": 400, "likes": 3, "reposts": 0, "replies": 1, "posted_at": "2026-09-05", "kind": "reply", "author": "agent"},
                              {"url": U2, "text": "owner post", "views": 50, "likes": 0, "reposts": 0, "replies": 0, "posted_at": "2026-09-05", "kind": "original", "author": "owner"}],
             "totals": {"views": 450, "likes": 3, "reposts": 0, "replies": 1}, "engagement_rate": 0.0089},
            {"date": "2026-09-05", "followers": 79, "following": 61, "posts_total": 56,
             "recent_posts": [{"url": U1, "text": "big one\nsecond line", "views": 300, "likes": 2, "reposts": 0, "replies": 1, "posted_at": "2026-09-05", "kind": "reply", "author": "agent"}],
             "totals": {"views": 300, "likes": 2, "reposts": 0, "replies": 1}, "engagement_rate": 0.01}]}
        s = stats.summary(data, now=NOW)
        lines = s.splitlines()
        self.assertLessEqual(len(lines), 10)
        self.assertIn("followers 81 (+2 in 2d, +2 vs prev day)", lines[0])
        self.assertIn("eng 0.89% (prev 1.00%)", s)
        self.assertRegex(s, r"400\s+\+100\s+3\s+1\s+reply\s+09-05\s+big one second line")  # d24h vs yesterday, newline flattened
        self.assertIn("owner posts in window: 1 · 50 views", s)
        self.assertNotIn("measured", s)  # 30 min old: fresh enough

    def test_stale_measurement_is_flagged(self):
        data = {"daily": [{"date": "2026-09-06", "followers": 81, "measured_at": "2026-09-05T20:00+00:00",
                           "recent_posts": [], "totals": {}, "engagement_rate": None}]}
        self.assertIn("measured 12h ago", stats.summary(data, now=NOW))

    def test_empty_file(self):
        self.assertEqual(stats.summary({"daily": []}), "stats.json: no data yet")


class Cli(unittest.TestCase):
    def test_record_then_summary_on_disk(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "stats.json")
            src = os.path.join(d, "env.json")
            open(src, "w").write(env(post(U1, "hello world", 7, 1)))
            self.assertEqual(stats.main(["--file", f, "record", "--followers", "80", "--from-status", src]), 0)
            data = json.load(open(f))
            self.assertEqual(data["daily"][0]["followers"], 80)
            self.assertEqual(data["daily"][0]["recent_posts"][0]["url"], U1)
            self.assertEqual(stats.main(["--file", f, "summary"]), 0)

    def test_record_with_nothing_is_an_error(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(stats.main(["--file", os.path.join(d, "s.json"), "record"]), 2)


if __name__ == "__main__":
    unittest.main()
