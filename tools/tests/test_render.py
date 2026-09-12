"""render.py: the safety gate refuses secrets, paths and blocking handles;
templates escape their data; html-only rendering writes no PNG."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import render  # noqa: E402

T0 = datetime(2026, 9, 7, 7, 0, tzinfo=timezone.utc)


class Scan(unittest.TestCase):
    def test_refuses_what_must_never_be_drawn(self):
        # fixtures are assembled at runtime so the file itself never holds a token-shaped literal
        cases = {
            "api key": "key sk-" + "abcdefghij" * 3,
            "github": "ghp" + "_" + "abcdefghij" * 3,
            "cookie": "auth" + "_token=deadbeef",
            "path": "see /home/someone/x_influencer",
            "ip": "cdp at 127.0.0.1:9223",
            "email": "mail me at a.b@example.com",
        }
        for name, text in cases.items():
            self.assertTrue(render.scan({"body": text}, blocked=set()), name)

    def test_employer_terms_come_from_the_private_file(self):
        import unittest.mock
        with unittest.mock.patch.object(render, "private_terms", lambda: ["Acme Corp"]):
            self.assertTrue(render.scan({"t": "we use acme corp"}, blocked=set()))
            self.assertEqual(render.scan({"t": "we use widgets"}, blocked=set()), [])

    def test_blocked_handle_is_refused_with_or_without_at(self):
        self.assertTrue(render.scan({"t": "blockerx blocked me"}, blocked={"blockerx"}))
        self.assertTrue(render.scan({"t": "cc @BlockerX"}, blocked={"blockerx"}))
        self.assertEqual(render.scan({"t": "two 500k accounts blocked me"}, blocked={"blockerx"}), [])

    def test_blocked_handles_come_from_state(self):
        st = {"do_not_reply": {"blockery": {"reason": "BLOCKED BY AUTHOR 09-06"}, "[account-5]": {"reason": "silent"}}}
        self.assertEqual(render.blocked_handles(st), {"blockery"})

    def test_clean_text_passes(self):
        self.assertEqual(render.scan({"title": "Day 8: 79 followers, +0", "body": "Replies got 800 views, zero conversation."}, blocked=set()), [])


class Templates(unittest.TestCase):
    def test_card_escapes_html(self):
        page = render.card_html("<b>x</b>", "a & b")
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", page)
        self.assertIn("a &amp; b", page)
        self.assertNotIn("<b>x</b>", page)

    def test_metrics_reads_series_and_yesterday(self):
        stats = {"daily": [
            {"date": "2026-09-06", "followers": 79, "totals": {"views": 5618}},
            {"date": "2026-09-05", "followers": 76, "totals": {"views": 4416}},
            {"date": "2026-08-30", "followers": 70, "totals": {"views": 120}}]}
        items = {"items": [
            {"kind": "original", "published": "2026-09-06T08:00+00:00", "snapshots": [{"profile_visits": 3}]},
            {"kind": "reply", "published": "2026-09-06T09:00+00:00", "snapshots": [{"profile_visits": 1}]},
            {"kind": "reply", "published": "2026-09-05T09:00+00:00", "snapshots": [{"profile_visits": 9}]}]}
        stats["daily"].insert(0, {"date": "2026-09-07", "followers": 80, "totals": {"views": 40}})  # today's partial row
        page, data = render.metrics_html(stats, items, days=14, today=T0)
        self.assertEqual(data, {"day": 9, "followers": 80, "delta_day": 1, "delta_window": 10, "views_yesterday": 5618,
                                "originals": 1, "replies": 1, "profile_visits": 4, "series_from": "2026-08-30"})
        self.assertIn("<polyline", page); self.assertIn("Day 9", page)

    def test_metrics_without_series_is_an_error(self):
        with self.assertRaises(ValueError):
            render.metrics_html({"daily": []}, {"items": []}, today=T0)


class Render(unittest.TestCase):
    def test_html_only_writes_html_and_refuses_dirty_data(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "c.png"
            p = render.render("card", render.card_html("t", "b"), {"title": "t", "body": "b"}, out, html_only=True)
            self.assertEqual(p, out.with_suffix(".html"))
            self.assertTrue(p.exists()); self.assertFalse(out.exists())
            with self.assertRaisesRegex(PermissionError, "local path"):
                render.render("card", "x", {"body": "/tmp/x"}, out, html_only=True)


if __name__ == "__main__":
    unittest.main()
