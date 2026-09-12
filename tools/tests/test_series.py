"""series.py: slots become due in their window, are done once items.json has
today's item, and models alternate per series until ab_until."""
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
import series  # noqa: E402

TZ = timezone(timedelta(hours=2))


def at(h, m=0, day=6):
    return datetime(2026, 9, day, h, m, tzinfo=TZ)


def items(*pairs):
    return {"items": [{"series": s, "published": t} for s, t in pairs]}


class Due(unittest.TestCase):
    def setUp(self):
        self.d = series.load(series.Path("/nonexistent"))

    def test_window_and_grace(self):
        self.assertEqual(series.due(self.d, {}, at(6, 20)), [])
        self.assertEqual(series.due(self.d, {}, at(6, 30)), ["metrics"])       # 60 min ahead
        self.assertEqual(series.due(self.d, {}, at(10, 0)), ["metrics"])       # late but within grace
        self.assertEqual(series.due(self.d, {}, at(14, 0)), ["take"])          # metrics past grace
        self.assertEqual(series.due(self.d, {}, at(21, 0)), ["postmortem"])

    def test_done_today_removes_it(self):
        it = items(("metrics", "2026-09-06T07:41+02:00"), ("take", "2026-09-05T13:10+02:00"))
        self.assertEqual(series.due(self.d, it, at(8, 0)), [])
        self.assertEqual(series.due(self.d, it, at(13, 0)), ["take"])          # yesterday's take does not count

    def test_done_today_ignores_items_without_a_readable_published(self):
        it = {"items": [{"series": "metrics"},                                 # no published at all
                        {"series": "metrics", "published": "not a date"},
                        {"series": "take", "published": "2026-09-06T13:05+02:00"}]}
        self.assertFalse(series.done_today(it, "metrics", at(8)))
        self.assertTrue(series.done_today(it, "take", at(14)))
        self.assertFalse(series.done_today({}, "take", at(14)))                # no items key


class Models(unittest.TestCase):
    def test_alternation_per_series_and_end_of_ab(self):
        d = series.load(series.Path("/nonexistent"))
        a, b = d["series"]["metrics"]["arms"]
        self.assertEqual(series.pick(d, "metrics", at(7)), a)
        self.assertEqual(series.pick(d, "metrics", at(7, day=7)), b)
        self.assertEqual(series.pick(d, "metrics", at(7, day=8)), a)
        self.assertEqual(series.pick(d, "take", at(13)), a)                    # independent per series
        self.assertEqual(series.next_model(d, None, at(9)), d["default_model"])
        after = datetime(2026, 9, 25, 7, tzinfo=TZ)
        d["default_model"] = "zai-coding-plan/other"
        self.assertEqual(series.pick(d, "metrics", after), "zai-coding-plan/other")  # A/B over: default model
        self.assertEqual(series.pick(d, "metrics", after), "zai-coding-plan/other")

    def test_single_arm_unknown_last_and_bad_ab_until(self):
        d = series.load(series.Path("/nonexistent"))
        d["series"]["take"]["arms"] = ["vendor/only"]
        self.assertEqual(series.next_model(d, "take", at(13)), "vendor/only")
        d["series"]["metrics"]["last"] = "vendor/retired"                       # last arm no longer in arms
        self.assertEqual(series.next_model(d, "metrics", at(7)), d["series"]["metrics"]["arms"][0])
        d["ab_until"] = "someday"                                               # unparseable: A/B stays on
        a, b = d["series"]["postmortem"]["arms"]
        d["series"]["postmortem"]["last"] = a
        self.assertEqual(series.next_model(d, "postmortem", at(21)), b)
        self.assertEqual(series.next_model(d, "nope", at(21)), d["default_model"])


class LoadSave(unittest.TestCase):
    def test_partial_file_gets_defaults_and_save_stamps_updated(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = series.Path(tmp) / "series.json"
            f.write_text(json.dumps({"default_model": "vendor/custom"}))
            d = series.load(f)
            self.assertEqual(d["default_model"], "vendor/custom")
            self.assertEqual(d["ab_until"], series.DEFAULT["ab_until"])
            self.assertEqual(set(d["series"]), {"metrics", "take", "postmortem"})
            d["series"]["metrics"]["last"] = "x"
            self.assertIsNone(series.DEFAULT["series"]["metrics"]["last"])     # defaults are copied, not shared
            series.save(d, f, at(9, 5))
            back = json.loads(f.read_text())
            self.assertEqual(back["updated"], "2026-09-06T09:05+02:00")
            self.assertEqual(back["default_model"], "vendor/custom")


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.f = os.path.join(self.tmp.name, "series.json")
        self.items = os.path.join(self.tmp.name, "items.json")

    def tearDown(self):
        self.tmp.cleanup()

    def run_(self, *args, now=at(7)):
        out, err = io.StringIO(), io.StringIO()
        with unittest.mock.patch.object(series, "_now", lambda: now), redirect_stdout(out), redirect_stderr(err):
            rc = series.main(["--file", self.f, "--items", self.items, *args])
        return rc, out.getvalue(), err.getvalue()

    def data(self):
        return json.loads(open(self.f).read())

    def write_items(self, *pairs):
        open(self.items, "w").write(json.dumps(items(*pairs)))

    def test_show_marks_posted_due_and_later(self):
        self.write_items(("metrics", "2026-09-06T07:41+02:00"))
        rc, out, _ = self.run_("show", now=at(12, 30))
        self.assertEqual(rc, 0)
        lines = {ln.split()[0]: ln for ln in out.splitlines() if ln.startswith("  ")}
        self.assertIn("posted", lines["metrics"])
        self.assertIn("DUE", lines["take"])
        self.assertIn("later", lines["postmortem"])
        self.assertIn("default model %s" % series.DEFAULT["default_model"], out)
        self.assertFalse(os.path.exists(self.f))                                # show never writes

    def test_due_honours_horizon(self):
        self.write_items(("metrics", "2026-09-06T07:41+02:00"))
        rc, out, _ = self.run_("due", now=at(12, 0))
        self.assertEqual((rc, json.loads(out)), (0, ["take"]))                  # 13:00 is 60 min away
        rc, out, _ = self.run_("due", "--horizon-min", "30", now=at(12, 0))
        self.assertEqual((rc, json.loads(out)), (0, []))
        rc, out, _ = self.run_("due", now=at(3, 0))                             # no items file at all
        self.assertEqual(json.loads(out), [])

    def test_model_without_series_prints_default_and_does_not_write(self):
        rc, out, _ = self.run_("model")
        self.assertEqual((rc, out.strip()), (0, series.DEFAULT["default_model"]))
        self.assertFalse(os.path.exists(self.f))

    def test_model_with_series_records_and_alternates(self):
        a, b = series.DEFAULT["series"]["metrics"]["arms"]
        rc, out, _ = self.run_("model", "metrics", now=at(7, 5))
        self.assertEqual((rc, out.strip()), (0, a))
        d = self.data()
        self.assertEqual(d["series"]["metrics"]["last"], a)
        self.assertEqual(d["series"]["metrics"]["last_at"], "2026-09-06T07:05+02:00")
        self.assertEqual(d["updated"], "2026-09-06T07:05+02:00")
        rc, out, _ = self.run_("model", "metrics", now=at(7, 5, day=7))
        self.assertEqual(out.strip(), b)
        self.assertIsNone(self.data()["series"]["take"]["last"])                # other series untouched

    def test_model_unknown_series(self):
        rc, out, err = self.run_("model", "weekly")
        self.assertEqual((rc, out), (2, ""))
        self.assertIn("unknown series weekly", err)
        self.assertFalse(os.path.exists(self.f))

    def test_set_default_and_set_arms(self):
        rc, out, _ = self.run_("set-default", "vendor/new-default")
        self.assertEqual(rc, 0); self.assertIn("vendor/new-default", out)
        self.assertEqual(self.data()["default_model"], "vendor/new-default")
        rc, out, _ = self.run_("model")
        self.assertEqual(out.strip(), "vendor/new-default")
        rc, out, _ = self.run_("set-arms", "take", "vendor/a", "vendor/b")
        self.assertEqual(rc, 0); self.assertIn("take arms: vendor/a | vendor/b", out)
        self.assertEqual(self.data()["series"]["take"]["arms"], ["vendor/a", "vendor/b"])
        self.assertEqual(self.data()["series"]["metrics"]["arms"], series.DEFAULT["series"]["metrics"]["arms"])
        rc, out, _ = self.run_("model", "take", now=at(13))
        self.assertEqual(out.strip(), "vendor/a")
        rc, out, _ = self.run_("model", "take", now=at(13, day=7))
        self.assertEqual(out.strip(), "vendor/b")


if __name__ == "__main__":
    unittest.main()
