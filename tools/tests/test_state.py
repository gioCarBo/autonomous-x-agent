"""state.py: working state as fields, daily counters that roll, a short show."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import state  # noqa: E402

U = "https://x.com/GCBullGlasses/status/2096098501612478659"


class Cli(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory(); self.f = os.path.join(self.d.name, "state.json")

    def tearDown(self):
        self.d.cleanup()

    def run_(self, *args):
        return state.main(["--file", self.f, *args])

    def data(self):
        return json.load(open(self.f))

    def test_hits_accumulate_today_and_cap_verb_is_retired(self):
        self.run_("hit", "[account-5]", U); self.run_("hit", "[account-5]", U); self.run_("hit", "[account-5]", U + "1")
        d = self.data()
        self.assertEqual(len(d["author_hits"]["hits"]["[account-5]"]), 2)  # same url once
        self.assertEqual(self.run_("cap", "reply"), 0)                 # no-op: the x CLI counts caps
        self.assertEqual(self.data()["caps"]["replies"], 0)

    def test_counters_roll_on_a_new_day(self):
        self.run_("hit", "[account-5]", U)
        d = self.data(); d["caps"].update({"date": "2000-01-01", "replies": 7, "likes": 3}); d["author_hits"]["date"] = "2000-01-01"
        json.dump(d, open(self.f, "w"))
        self.run_("hit", "[account-5]", U)
        c = self.data()["caps"]
        self.assertEqual((c["replies"], c["likes"], c["follows"], c["post_times"]), (0, 0, 0, []))
        self.assertEqual(self.data()["author_hits"]["hits"], {"[account-5]": [U]})

    def test_readout_lifecycle(self):
        self.assertEqual(self.run_("readout", "add", U, "announcement", "--due", "2026-09-06T06:50+02:00"), 0)
        self.run_("readout", "touch", U, "--views", "94", "--likes", "1", "--note", "x" * 200)
        r = self.data()["readouts"][0]
        self.assertEqual((r["status"], r["last"]["views"], len(r["last"]["note"])), ("open", 94, 120))
        self.assertEqual(r["due"], "2026-09-06T06:50+02:00")
        self.run_("readout", "close", U, "--verdict", "stall-class")
        r = self.data()["readouts"][0]
        self.assertEqual((r["status"], r["verdict"]), ("closed", "stall-class"))
        self.assertEqual(self.run_("readout", "touch", "https://x.com/a/status/9", "--views", "1"), 2)

    def test_dnr_angles_deadlines_targets(self):
        self.run_("dnr", "add", "[account-2]", "silent on ours")
        self.run_("angle", "add", "failed-population eval"); self.run_("angle", "add", "failed-population eval")
        self.run_("deadline", "add", "ab-first-original", "2026-09-06T06:50+02:00")
        self.run_("deadline", "add", "ab-first-original", "2026-09-06T07:50+02:00")  # replaces
        self.run_("targets", "set", "@karpathy", "[account-5]")
        d = self.data()
        self.assertIn("[account-2]", d["do_not_reply"])
        self.assertEqual(d["used_angles"], ["failed-population eval"])
        self.assertEqual([x["at"] for x in d["deadlines"]], ["2026-09-06T07:50+02:00"])
        self.assertEqual(d["targets"], ["karpathy", "[account-5]"])
        self.run_("dnr", "clear", "[account-2]"); self.run_("deadline", "clear", "ab-first-original")
        d = self.data()
        self.assertEqual((d["do_not_reply"], d["deadlines"]), ({}, []))

    def test_short_keys_prefix_and_id_tail(self):
        self.run_("deadline", "add", "[account-1]-exif-carry", "2026-09-06T03:13+02:00", "--note", "draft in wake-0100 log")
        self.run_("deadline", "add", "no-modal-watch", "2026-09-06T23:59+02:00")
        self.assertEqual(self.run_("deadline", "clear", "[account-1]"), 0)          # unique prefix
        self.assertEqual([x["label"] for x in self.data()["deadlines"]], ["no-modal-watch"])
        self.assertEqual(self.run_("deadline", "clear", "nothing-like-this"), 2)  # unknown -> rc 2, state intact
        self.assertEqual(len(self.data()["deadlines"]), 1)
        self.run_("readout", "add", U, "announcement")
        self.assertEqual(self.run_("readout", "touch", "2096098501612478659", "--views", "5"), 0)  # id tail
        self.assertEqual(self.data()["readouts"][0]["last"]["views"], 5)

    def test_readout_by_the_eight_digit_tail_the_tools_print(self):
        # `show`, stats.py and precheck all print …12478659; the 06:09 09-06 wake
        # typed exactly that and got "no readout" — the tail matcher wanted the full id.
        self.run_("readout", "add", U, "announcement")
        self.assertEqual(self.run_("readout", "touch", "12478659", "--views", "104"), 0)
        self.assertEqual(self.run_("readout", "close", "12478659", "--verdict", "no-distribution"), 0)
        r = self.data()["readouts"][0]
        self.assertEqual((r["last"]["views"], r["status"], r["verdict"]), (104, "closed", "no-distribution"))
        self.run_("readout", "add", "https://x.com/a/status/9999912478659", "twin")   # same tail → ambiguous
        self.assertEqual(self.run_("readout", "touch", "12478659", "--views", "1"), 2)
        self.assertEqual(self.run_("readout", "touch", "diary", "--views", "1"), 2)   # words never match ids

    def test_readout_add_takes_a_bare_id_and_a_note(self):
        # The 06:07 wake chained `readout add … --note …` && `deadline add …`; the
        # unknown flag aborted the chain and the A/B deadline was never written.
        self.assertEqual(self.run_("readout", "add", "2096450478670242098", "diary-ab-1",
                                   "--due", "2026-09-09T07:00+02:00", "--note", "A/B item 1 (diary)"), 0)
        r = self.data()["readouts"][0]
        self.assertEqual(r["url"], "https://x.com/i/status/2096450478670242098")
        self.assertEqual((r["label"], r["note"]), ("diary-ab-1", "A/B item 1 (diary)"))
        self.assertEqual(self.run_("readout", "touch", "70242098", "--views", "16"), 0)   # tail of a bare-id add
        self.assertEqual(self.run_("readout", "touch", "2096450478670242098", "--views", "17"), 0)
        self.assertEqual(len(self.data()["readouts"]), 1)


class Show(unittest.TestCase):
    def test_show_is_compact_and_flags_what_is_due(self):
        now = datetime(2026, 9, 6, 8, 0, tzinfo=timezone(timedelta(hours=2)))
        d = state.load(__import__("pathlib").Path("/nonexistent"))
        d["caps"].update({"date": "2026-09-06", "replies": 8, "originals": 1})
        d["author_hits"] = {"date": "2026-09-06", "hits": {"[account-5]": [U, U + "1"]}}
        d["readouts"] = [{"url": U, "label": "announcement", "opened": "2026-09-05T06:50+02:00", "due": "2026-09-06T06:50+02:00",
                          "status": "open", "last": {"t": "2026-09-05T22:05+02:00", "views": 94, "likes": 1, "note": "24h verdict pending"}},
                         {"url": U + "2", "label": "closed one", "opened": "2026-09-05T06:50+02:00", "status": "closed", "last": None}]
        d["deadlines"] = [{"label": "ab-first-original", "at": "2026-09-06T06:50+02:00"}, {"label": "far", "at": "2026-09-30T00:00+02:00"}]
        d["do_not_reply"] = {"quietguy": {"reason": "silent on ours", "since": "x"}}
        d["used_angles"] = ["a"] * 10
        d["targets"] = ["karpathy", "[account-5]"]
        s = state.show(d, now)
        lines = s.splitlines()
        self.assertLessEqual(len(lines), 15)
        self.assertEqual(lines[0], "caps 2026-09-06 (counted by the x CLI): replies 8/25 · originals+quotes 1/5 · likes 0/30 · reposts 0/2 · follows 0/3")
        self.assertIn("[account-5]×2", s)
        self.assertIn("  ab-first-original 09-06T06:50 OVERDUE", s)
        self.assertNotIn("far", s)                      # >24h away: not shown
        self.assertIn("open readouts (1):", s)          # closed one hidden
        self.assertIn("announcement                 t+25h  94v 1L due 09-06T06:50 — 24h verdict pending", s)
        self.assertIn("  quietguy      silent on ours", s)
        self.assertIn("used angles (10,", s)
        self.assertIn("targets: 2 (karpathy [account-5])", s)


if __name__ == "__main__":
    unittest.main()
