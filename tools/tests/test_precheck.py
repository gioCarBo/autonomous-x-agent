"""precheck.py: skip only when every deterministic signal is quiet; any doubt launches."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import precheck  # noqa: E402

TZ = timezone(timedelta(hours=2))
NOW = datetime(2026, 9, 6, 9, 0, tzinfo=TZ)
LAST = NOW - timedelta(minutes=58)            # previous hourly wake ran the LLM
STATE = {"targets": ["[account-5]", "karpathy"], "deadlines": [], "readouts": []}
QUIET_NOTIF = {"n": 1, "items": [{"actors": ["/x"], "time": (LAST - timedelta(hours=5)).isoformat()}]}
QUIET_SWEEP = {"handles": [{"handle": "[account-5]", "fresh": [{"age_min": 170}]}, {"handle": "karpathy", "fresh": []}], "errors": []}


def d(**kw):
    args = dict(now=NOW, last_llm=LAST, state=STATE, notif=QUIET_NOTIF, sweep=QUIET_SWEEP)
    args.update(kw)
    return precheck.decide(**args)


class Decide(unittest.TestCase):
    def test_quiet_hour_is_a_skip(self):
        self.assertEqual(d(), (False, ["quiet"]))  # the 170-min post predates the last LLM wake

    def test_new_notification_launches(self):
        n = {"items": [{"actors": ["/[account-4]"], "time": (NOW - timedelta(minutes=10)).isoformat()}]}
        self.assertEqual(d(notif=n), (True, ["notification:/[account-4]"]))

    def test_fresh_post_since_last_wake_launches(self):
        s = {"handles": [{"handle": "karpathy", "fresh": [{"age_min": 12}]}], "errors": []}
        self.assertEqual(d(sweep=s), (True, ["fresh:karpathy@12min"]))

    def test_deadline_and_readout_inside_the_horizon_launch(self):
        st = dict(STATE, deadlines=[{"label": "ab-first", "at": (NOW + timedelta(minutes=50)).isoformat()},
                                    {"label": "far", "at": (NOW + timedelta(hours=9)).isoformat()}],
                  readouts=[{"url": "https://x.com/a/status/12345678", "status": "open", "due": (NOW - timedelta(minutes=5)).isoformat()},
                            {"url": "https://x.com/a/status/2", "status": "closed", "due": NOW.isoformat()}])
        self.assertEqual(d(state=st), (True, ["deadline:ab-first", "readout-due:12345678"]))

    def test_every_failure_mode_launches(self):
        self.assertEqual(d(last_llm=None), (True, ["no-marker"]))
        self.assertEqual(d(notif=None)[1], ["notifications-failed"])
        self.assertEqual(d(sweep=None)[1], ["sweep-failed"])
        self.assertEqual(d(sweep={"handles": [], "errors": [{"handle": "x"}]})[1], ["sweep-empty"])
        self.assertEqual(d(state={"targets": []})[1], ["no-targets"])

    def test_fresh_post_by_a_blocking_author_is_no_signal(self):
        # 07:01 09-06: launched for fresh:[account-2] four hours after he blocked us.
        st = dict(STATE, do_not_reply={"[account-2]": {"reason": "BLOCKED BY AUTHOR (X modal …)", "since": "x"},
                                       "[account-3]": {"reason": "no 2nd reply unless he engages", "since": "x"}})
        s = {"handles": [{"handle": "[account-2]", "fresh": [{"age_min": 25}]},
                         {"handle": "[account-3]", "fresh": []}], "errors": []}
        self.assertEqual(d(state=st, sweep=s), (False, ["quiet"]))
        s["handles"][1]["fresh"] = [{"age_min": 12}]                       # soft dnr still counts
        self.assertEqual(d(state=st, sweep=s), (True, ["fresh:[account-3]@12min"]))
        self.assertEqual(precheck.blocked_authors(st), {"[account-2]"})
        self.assertEqual(precheck.blocked_authors({}), set())

    def test_a_like_is_labelled_and_does_not_launch_alone(self):
        # 09:02 09-06: a like carrying the liked post's text launched a full wake.
        fresh = (NOW - timedelta(minutes=10)).isoformat()
        like = {"items": [{"actors": ["/Heyotter666"], "time": fresh, "kind": "like", "text": "…"}]}
        self.assertEqual(d(notif=like), (False, ["like:/Heyotter666"]))
        reply = {"items": [like["items"][0], {"actors": ["/[account-4]"], "time": fresh, "kind": "reply"}]}
        self.assertEqual(d(notif=reply), (True, ["like:/Heyotter666", "notification:/[account-4]"]))
        legacy = {"items": [{"actors": ["/x"], "time": fresh}]}           # no kind → hard, as before
        self.assertEqual(d(notif=legacy), (True, ["notification:/x"]))

    def test_long_silence_forces_a_wake(self):
        nothing = {"handles": [{"handle": "[account-5]", "fresh": []}], "errors": []}
        self.assertEqual(d(last_llm=NOW - timedelta(hours=3, minutes=1), sweep=nothing), (True, ["silence:181min"]))
        self.assertEqual(d(last_llm=NOW - timedelta(hours=2, minutes=59), sweep=nothing), (False, ["quiet"]))

    def test_z_suffix_times_parse(self):
        n = {"items": [{"actors": ["/a"], "time": (NOW - timedelta(minutes=1)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")}]}
        self.assertTrue(d(notif=n)[0])


class Main(unittest.TestCase):
    def run_main(self, runner, marker_text=LAST.isoformat(), state=STATE, argv=(), series_name="no-series.json"):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "marker").write_text(marker_text)
            (tmp / "state.json").write_text(json.dumps(state))
            rc = precheck.main(list(argv), runner=runner, now=NOW, marker=tmp / "marker",
                               state_file=tmp / "state.json", latest=tmp / "latest.json",
                               series_file=tmp / series_name, items_file=tmp / "items.json")
            return rc, json.loads((tmp / "latest.json").read_text())

    def test_skip_exit_code_and_saved_envelopes(self):
        calls = []

        def runner(args, timeout):
            calls.append(args)
            return QUIET_NOTIF if args[0] == "notifications" else QUIET_SWEEP
        rc, latest = self.run_main(runner)
        self.assertEqual(rc, precheck.SKIP)
        self.assertEqual(latest["launch"], False)
        self.assertEqual(latest["sweep"], QUIET_SWEEP)              # reusable by the launched wake
        self.assertEqual(calls[0], ["notifications", "--limit", "20"])
        self.assertEqual(calls[1][:3], ["sweep", "[account-5]", "karpathy"])
        self.assertIn("--since", calls[1])

    def test_verb_failure_launches_with_exit_0(self):
        rc, latest = self.run_main(lambda args, timeout: None)
        self.assertEqual(rc, 0)
        self.assertEqual(latest["reasons"], ["notifications-failed", "sweep-failed"])

    def test_series_slot_launches_and_sweep_rotates(self):
        calls = []

        def runner(args, timeout):
            calls.append(args); return QUIET_NOTIF if args[0] == "notifications" else QUIET_SWEEP
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "marker").write_text(LAST.isoformat())
            many = ["h%02d" % i for i in range(45)]
            (tmp / "state.json").write_text(json.dumps({**STATE, "targets": many}))
            (tmp / "series.json").write_text(json.dumps({"series": {"metrics": {"at": "09:30", "arms": ["a", "b"]}}}))
            kw = dict(runner=runner, now=NOW, marker=tmp / "marker", state_file=tmp / "state.json",
                      latest=tmp / "latest.json", series_file=tmp / "series.json", items_file=tmp / "items.json")
            rc = precheck.main(["--sweep-max", "20"], **kw)
            latest = json.loads((tmp / "latest.json").read_text())
            self.assertEqual((rc, latest["reasons"], latest["series_due"]), (0, ["series:metrics"], ["metrics"]))
            self.assertEqual(calls[1][1:21], many[:20])                       # first slice
            precheck.main(["--sweep-max", "20"], **kw)
            self.assertEqual(calls[3][1:21], many[20:40])                     # rotated
            precheck.main(["--sweep-max", "20"], **kw)
            self.assertEqual(calls[5][1:21], many[40:] + many[:15])           # wraps

    def test_launch_mode_shrinks_the_sweep(self):
        calls = []

        def runner(args, timeout):
            calls.append(args); return QUIET_NOTIF if args[0] == "notifications" else QUIET_SWEEP
        many = ["h%02d" % i for i in range(18)]
        rc, latest = self.run_main(runner, state={**STATE, "targets": many, "launch_mode": {"since": "x"}},
                                   argv=["--sweep-max", "20", "--pace", "10"])
        self.assertEqual(rc, precheck.SKIP)
        self.assertEqual(calls[1][1:1 + precheck.LAUNCH_SWEEP_MAX], many[:precheck.LAUNCH_SWEEP_MAX])
        self.assertEqual(calls[1][1 + precheck.LAUNCH_SWEEP_MAX], "--since")   # exactly 6 handles swept
        self.assertEqual(calls[1][-1], str(precheck.LAUNCH_PACE))
        self.assertTrue(latest["launch_mode"])

    def test_missing_marker_launches_without_touching_x(self):
        calls = []

        def runner(args, timeout):
            calls.append(args); return QUIET_NOTIF if args[0] == "notifications" else QUIET_SWEEP
        rc, latest = self.run_main(runner, marker_text="garbage")
        self.assertEqual((rc, latest["reasons"]), (0, ["no-marker"]))


if __name__ == "__main__":
    unittest.main()
