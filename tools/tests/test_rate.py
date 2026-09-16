"""rate.py: one rating per post (re-rating overwrites), joined to items.json."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rate  # noqa: E402

T0 = datetime(2026, 9, 7, 9, 0, tzinfo=timezone.utc)
U = "https://x.com/GCBullGlasses/status/1"


def item(sid, kind="original", series="take", model="vendor/model-a", text="a", published="2026-09-06T10:00+00:00"):
    return {"status_id": sid, "url": U[:-1] + sid, "kind": kind, "series": series, "model": model,
            "text": text, "published": published}


class Rate(unittest.TestCase):
    def test_add_overwrites_and_validates(self):
        d = rate.load(rate.Path("/nonexistent"))
        rate.add(d, U, 6, "fine", T0)
        rate.add(d, "1", 8, "better on reread", T0)
        self.assertEqual(len(d["ratings"]), 1)
        self.assertEqual(d["ratings"][0]["score"], 8)
        with self.assertRaises(ValueError):
            rate.add(d, U, 11, "x", T0)

    def test_show_and_pending(self):
        d = rate.load(rate.Path("/nonexistent"))
        items = {"items": [{"status_id": "1", "url": U, "kind": "original", "series": "take", "model": "zai/glm-5.3", "text": "a", "published": "2026-09-06T10:00+00:00"},
                           {"status_id": "2", "url": U[:-1] + "2", "kind": "reply", "series": None, "model": "zai/glm-5.3-flash", "text": "b", "published": "2026-09-06T11:00+00:00"}]}
        rate.add(d, U, 7, "ok", T0)
        s = rate.show(d, items, T0)
        self.assertIn("mean 7.0", s); self.assertIn("take", s)
        p = rate.pending(d, items)
        self.assertIn("status/2", p); self.assertNotIn("status/1 ", p)


class Add(unittest.TestCase):
    def setUp(self):
        self.d = rate.load(rate.Path("/nonexistent"))

    def test_status_id_forms(self):
        self.assertEqual(rate.status_id(U), "1")
        self.assertEqual(rate.status_id(U + "/"), "1")
        self.assertEqual(rate.status_id(U + "/photo/1"), "1")
        self.assertEqual(rate.status_id("123"), "123")
        self.assertIsNone(rate.status_id("https://x.com/someone"))
        self.assertIsNone(rate.status_id("abc"))
        self.assertIsNone(rate.status_id(""))

    def test_bare_id_and_first_rating(self):
        r = rate.add(self.d, "123", 9, "y" * 300, T0)
        self.assertEqual(r["status_id"], "123"); self.assertEqual(r["url"], "123")
        self.assertEqual(len(r["why"]), 200)                                   # why is capped
        self.assertEqual(r["t"], "2026-09-07T09:00+00:00")
        self.assertEqual(self.d["ratings"], [r])

    def test_validation_errors_leave_the_list_untouched(self):
        for url, score in ((U, 0), (U, 11), (U, -3), ("https://x.com/someone", 5), ("not a url", 5)):
            with self.assertRaises(ValueError):
                rate.add(self.d, url, score, "why", T0)
        self.assertEqual(self.d["ratings"], [])
        with self.assertRaises(ValueError) as cm:
            rate.add(self.d, U, 0, "why", T0)
        self.assertIn("1-10", str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            rate.add(self.d, "nope", 5, "why", T0)
        self.assertIn("not a status URL", str(cm.exception))

    def test_upsert_keeps_original_url_and_bumps_time(self):
        rate.add(self.d, U, 6, "first", T0)
        later = T0 + timedelta(days=1)
        r = rate.add(self.d, U + "/photo/1", 4, "second look", later)
        self.assertEqual(len(self.d["ratings"]), 1)
        self.assertEqual((r["score"], r["why"], r["t"]), (4, "second look", "2026-09-08T09:00+00:00"))
        self.assertEqual(r["url"], U)                                          # original url kept
        rate.add(self.d, U[:-1] + "2", 8, "other post", T0)
        self.assertEqual([r["status_id"] for r in self.d["ratings"]], ["1", "2"])


class Show(unittest.TestCase):
    def setUp(self):
        self.d = rate.load(rate.Path("/nonexistent"))
        self.items = {"items": [item("1", model="vendor/model-a", text="first line\nsecond line"),
                                item("2", kind="reply", series=None, model="vendor/model-b", text="b")]}

    def test_empty(self):
        self.assertEqual(rate.show(self.d, self.items, T0), "ratings: none in 14d")
        self.assertEqual(rate.show(self.d, {}, T0, days=3), "ratings: none in 3d")
        rate.add(self.d, U, 7, "old", T0 - timedelta(days=20))
        self.assertEqual(rate.show(self.d, self.items, T0), "ratings: none in 14d")   # outside the window
        self.assertIn("mean 7.0", rate.show(self.d, self.items, T0, days=30))

    def test_joined_to_items_single_model_has_no_by_model_line(self):
        rate.add(self.d, U, 7, "ok", T0)
        s = rate.show(self.d, self.items, T0)
        lines = s.splitlines()
        self.assertEqual(lines[0], "ratings 14d: 1 · mean 7.0")
        self.assertIn("original", lines[1]); self.assertIn("take", lines[1]); self.assertIn("model-a", lines[1])
        self.assertIn("first line second line", lines[1])                       # newline flattened
        self.assertIn("— ok", lines[1])
        self.assertNotIn("by model", s)

    def test_by_model_line_with_two_models_and_unknown_items(self):
        rate.add(self.d, U, 8, "sharp", T0 - timedelta(hours=2))
        rate.add(self.d, U[:-1] + "2", 4, "flat", T0 - timedelta(hours=1))
        rate.add(self.d, U[:-1] + "9", 6, "not in items", T0)
        s = rate.show(self.d, self.items, T0)
        lines = s.splitlines()
        self.assertEqual(lines[0], "ratings 14d: 3 · mean 6.0")
        self.assertTrue(lines[1].startswith(" 6  ?"))                           # newest first, unknown item shows ?
        self.assertIn("status/9", lines[1])                                    # url stands in for the text
        self.assertTrue(lines[2].startswith(" 4  reply"))
        self.assertTrue(lines[3].startswith(" 8  original"))
        self.assertEqual(lines[4], "by model: - 6.0 (n=1) · model-a 8.0 (n=1) · model-b 4.0 (n=1)")


class Pending(unittest.TestCase):
    def setUp(self):
        self.d = rate.load(rate.Path("/nonexistent"))
        self.items = {"items": [item("1", published="2026-09-06T10:00+00:00"),
                                item("2", kind="reply", series=None, published="2026-09-06T12:00+00:00", text="newest\nreply"),
                                item("3", published="2026-09-06T11:00+00:00")]}

    def test_nothing_to_rate(self):
        self.assertEqual(rate.pending(self.d, {}), "nothing to rate")
        for sid in "123":
            rate.add(self.d, sid, 5, "x", T0)
        self.assertEqual(rate.pending(self.d, self.items), "nothing to rate")

    def test_newest_first_and_n_caps_the_list(self):
        rate.add(self.d, "3", 5, "x", T0)
        p = rate.pending(self.d, self.items)
        lines = p.splitlines()
        self.assertEqual(lines[0], 'unrated (2 shown of 2) — rate.py add <url> <1-10> "why"')
        self.assertTrue(lines[1].startswith(U[:-1] + "2  reply    -  ")); self.assertIn("newest reply", lines[1])
        self.assertTrue(lines[2].startswith(U + "  original take"))
        self.assertNotIn("status/3", p)
        p = rate.pending(self.d, self.items, n=1)
        self.assertEqual(len(p.splitlines()), 2); self.assertIn("(1 shown of 2)", p)


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.f = os.path.join(self.tmp.name, "ratings.json")
        self.items = os.path.join(self.tmp.name, "items.json")

    def tearDown(self):
        self.tmp.cleanup()

    def run_(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with unittest.mock.patch.object(rate, "_now", lambda: T0), redirect_stdout(out), redirect_stderr(err):
            rc = rate.main(["--file", self.f, "--items", self.items, *args])
        return rc, out.getvalue(), err.getvalue()

    def data(self):
        return json.loads(open(self.f).read())

    def test_add_writes_the_file(self):
        rc, out, _ = self.run_("add", U + "2345678", "6", "decent hook, weak close")
        self.assertEqual((rc, out.strip()), (0, "rated …12345678 6/10"))
        d = self.data()
        self.assertEqual(len(d["ratings"]), 1)
        self.assertEqual(d["ratings"][0]["status_id"], "12345678")
        self.assertEqual(d["ratings"][0]["t"], "2026-09-07T09:00+00:00")
        rc, out, _ = self.run_("add", "12345678", "9", "aged well")
        self.assertEqual(out.strip(), "rated …12345678 9/10")
        self.assertEqual([r["score"] for r in self.data()["ratings"]], [9])

    def test_add_rejects_bad_score_and_url(self):
        rc, out, err = self.run_("add", U, "12", "too high")
        self.assertEqual((rc, out), (2, "")); self.assertIn("score must be 1-10", err)
        self.assertFalse(os.path.exists(self.f))                                # nothing written
        rc, _, err = self.run_("add", "https://x.com/someone", "5", "profile, not a post")
        self.assertEqual(rc, 2); self.assertIn("not a status URL", err)
        self.assertFalse(os.path.exists(self.f))

    def test_show_and_pending_on_disk(self):
        open(self.items, "w").write(json.dumps({"items": [item("1"), item("2", kind="reply", series=None, model="vendor/model-b")]}))
        rc, out, _ = self.run_("show")
        self.assertEqual((rc, out.strip()), (0, "ratings: none in 14d"))
        rc, out, _ = self.run_("pending")
        self.assertEqual(rc, 0); self.assertIn("(2 shown of 2)", out)
        self.run_("add", U, "7", "ok")
        rc, out, _ = self.run_("show", "--days", "30")
        self.assertEqual(rc, 0); self.assertIn("ratings 30d: 1 · mean 7.0", out); self.assertNotIn("by model", out)
        rc, out, _ = self.run_("pending", "--n", "1")
        self.assertEqual(rc, 0); self.assertIn("(1 shown of 1)", out); self.assertIn("status/2", out)

    def test_show_and_pending_without_files(self):
        rc, out, _ = self.run_("show")
        self.assertEqual((rc, out.strip()), (0, "ratings: none in 14d"))
        rc, out, _ = self.run_("pending")
        self.assertEqual((rc, out.strip()), (0, "nothing to rate"))


if __name__ == "__main__":
    unittest.main()
