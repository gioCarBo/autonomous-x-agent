"""targets.py: eligibility is a rule (followers band, answers strangers, bio
exclusions, never a blocker); review drops what earned nothing."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import targets  # noqa: E402

T0 = datetime(2026, 9, 7, 9, 0, tzinfo=timezone.utc)


def prof(followers="12.4K", bio="builds agents, writes about evals"):
    return {"handle": "x", "counts": {"followers": followers}, "bio": bio}


def act(rep=9, dist=6):
    return {"replies_to_others": rep, "distinct_accounts": dist}


class Verdict(unittest.TestCase):
    def test_eligible(self):
        v = targets.verdict("someone", prof(), act(), {})
        self.assertTrue(v["eligible"]); self.assertEqual((v["followers"], v["replies_7d"]), (12400, 9))

    def test_reasons(self):
        self.assertIn("outside", targets.verdict("a", prof("240K"), act(), {})["reasons"][0])
        self.assertIn("outside", targets.verdict("a", prof("900"), act(), {})["reasons"][0])
        self.assertIn("exclusion", targets.verdict("a", prof(bio="crypto degen, buy my course"), act(), {})["reasons"][0])
        self.assertIn("too little", targets.verdict("a", prof(), act(2, 2), {})["reasons"][0])
        self.assertIn("blocked", targets.verdict("blockerx", prof(), act(),
                                                 {"do_not_reply": {"blockerx": {"reason": "BLOCKED BY AUTHOR 09-06"}}})["reasons"][0])
        self.assertIn("mega", targets.verdict("bigvoice", prof(), act(), {"megas": ["bigvoice"]})["reasons"][0])
        v = targets.verdict("a", None, None, {})
        self.assertEqual(len(v["reasons"]), 2)


class Count(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(targets._count("12,5K"), 12500)
        self.assertEqual(targets._count("12.4K"), 12400)
        self.assertEqual(targets._count("1.234"), 1234)          # thousands separator, not a decimal
        self.assertEqual(targets._count("1,234"), 1234)
        self.assertEqual(targets._count("3M"), 3_000_000)
        self.assertEqual(targets._count("2,1 m"), 2_100_000)
        self.assertEqual(targets._count(" 77 "), 77)
        self.assertEqual(targets._count(42), 42)
        self.assertIsNone(targets._count(None))
        self.assertIsNone(targets._count("garbage"))
        self.assertIsNone(targets._count(""))
        self.assertIsNone(targets._count("K"))


class RunVerb(unittest.TestCase):
    def run_with(self, fake):
        err = io.StringIO()
        with unittest.mock.patch.object(subprocess, "run", fake), redirect_stderr(err):
            return targets.run_verb(["profile", "someone"], 5), err.getvalue()

    @staticmethod
    def completed(rc, stdout):
        return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr="")

    def test_evidence_from_last_json_line(self):
        out, _ = self.run_with(lambda *a, **k: self.completed(0, 'progress line\n{"ok": true, "evidence": {"bio": "x"}}\n'))
        self.assertEqual(out, {"bio": "x"})

    def test_failures_are_none(self):
        self.assertIsNone(self.run_with(lambda *a, **k: self.completed(1, '{"evidence": {}}'))[0])
        self.assertIsNone(self.run_with(lambda *a, **k: self.completed(0, "not json"))[0])
        self.assertIsNone(self.run_with(lambda *a, **k: self.completed(0, ""))[0])
        self.assertIsNone(self.run_with(lambda *a, **k: self.completed(0, "[1, 2]"))[0])      # no .get
        self.assertIsNone(self.run_with(lambda *a, **k: self.completed(0, '{"ok": true}'))[0])  # no evidence key

    def test_timeout_and_missing_binary(self):
        def boom(*a, **k):
            raise subprocess.TimeoutExpired(cmd="x", timeout=k.get("timeout"))
        out, err = self.run_with(boom)
        self.assertIsNone(out); self.assertIn("profile failed", err)

        def missing(*a, **k):
            raise FileNotFoundError("x")
        self.assertIsNone(self.run_with(missing)[0])

    def test_passes_xcli_and_timeout(self):
        seen = {}

        def fake(cmd, **k):
            seen.update(cmd=cmd, timeout=k.get("timeout"))
            return self.completed(0, '{"evidence": {}}')
        self.run_with(fake)
        self.assertEqual(seen["cmd"], [str(targets.XCLI), "profile", "someone"])
        self.assertEqual(seen["timeout"], 5)


class Evaluate(unittest.TestCase):
    def test_runner_calls_and_verdict(self):
        calls = []

        def runner(args, timeout):
            calls.append((tuple(args), timeout))
            return prof() if args[0] == "profile" else act()
        v = targets.evaluate("someone", {}, runner=runner)
        self.assertTrue(v["eligible"])
        self.assertEqual(calls, [(("profile", "someone"), 120), (("replies", "someone"), 150)])

    def test_unreadable_runner(self):
        v = targets.evaluate("someone", {}, runner=lambda args, timeout: None)
        self.assertFalse(v["eligible"])
        self.assertEqual(v["reasons"], ["follower count unreadable", "reply activity unreadable"])


class Review(unittest.TestCase):
    def test_drop_rule_and_log(self):
        items = {"items": [{"kind": "reply", "parent_handle": "quiet", "author_replied": None}] * 10
                 + [{"kind": "reply", "parent_handle": "chatty", "author_replied": True}] * 3
                 + [{"kind": "reply", "parent_handle": "chatty", "author_replied": None}] * 9}
        state = {"targets": ["quiet", "chatty", "fresh"], "megas": [], "target_meta": {}}
        logged = []
        out = targets.review(state, items, T0, log=lambda t, n: logged.append(t))
        self.assertEqual(state["targets"], ["chatty", "fresh"])
        self.assertEqual(len(logged), 1); self.assertIn("@quiet", logged[0])
        self.assertEqual(targets.our_record("chatty", items), (12, 3))
        self.assertIn("below the floor", out[-1])

    def test_drop_writes_the_log_file_and_marks_meta(self):
        items = {"items": [{"kind": "reply", "parent_handle": "Quiet", "author_replied": None}] * 10
                 + [{"kind": "original", "parent_handle": "quiet"}]}                    # not a reply: not counted
        state = {"targets": ["quiet"], "megas": [], "target_meta": {"quiet": {"followers": 9000}}}
        with tempfile.TemporaryDirectory() as tmp:
            log = targets.Path(tmp) / "targets-log.md"
            out = targets.review(state, items, T0, log=lambda t, n: targets.log_line(t, n, log))
            text = log.read_text()
        self.assertTrue(text.startswith("# Target list changes"))
        self.assertIn("- 2026-09-07 09:00 - @quiet: 10 of our replies, 0 answers from the author (rule)", text)
        self.assertEqual(state["targets"], [])
        self.assertEqual(state["target_meta"]["quiet"]["dropped"], "2026-09-07T09:00+00:00")
        self.assertEqual(state["target_meta"]["quiet"]["our_replies"], 10)
        self.assertTrue(out[0].startswith("quiet")); self.assertIn("DROP", out[0]); self.assertIn("9000", out[0])

    def test_nothing_to_drop(self):
        state = {"targets": ["fresh"], "megas": [], "target_meta": {}}
        out = targets.review(state, {}, T0, log=lambda t, n: self.fail("nothing should be logged"))
        self.assertEqual(state["targets"], ["fresh"])
        self.assertEqual(state["target_meta"]["fresh"], {"our_replies": 0, "author_replies": 0})
        self.assertNotIn("DROP", out[0])


class Show(unittest.TestCase):
    def test_lists_targets_with_meta_and_megas(self):
        state = {"targets": ["known", "bare"], "megas": ["bigvoice", "loudone"],
                 "target_meta": {"known": {"followers": 12400, "replies_7d": 9, "distinct_7d": 6, "our_replies": 4, "author_replies": 1}}}
        s = targets.show(state)
        lines = s.splitlines()
        self.assertEqual(lines[0], "targets (2, mid-tier, swept by precheck):")
        self.assertIn("known", lines[1]); self.assertIn("12400 followers  9 replies/7d to 6  ours 1/4 answered", lines[1])
        self.assertIn("bare", lines[2]); self.assertIn("? followers  ? replies/7d to ?  ours 0/0 answered", lines[2])
        self.assertEqual(lines[3], "megas (2, max 1 reply/day, unique angle only): bigvoice loudone")

    def test_empty(self):
        s = targets.show({"targets": [], "megas": [], "target_meta": {}})
        self.assertEqual(s, "targets (0, mid-tier, swept by precheck):\nmegas (0, max 1 reply/day, unique angle only): ")


class Cli(unittest.TestCase):
    """main() reads STATE/ITEMS from the module, but LOG is bound as log_line's
    default and log_line is bound as review's default, both at import time:
    the only patch that reaches every log write is log_line's own default."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = targets.Path(self.tmp.name)
        self.state, self.items, self.log = root / "state.json", root / "items.json", root / "targets-log.md"
        self.write_state({"targets": ["known"], "megas": ["bigvoice"],
                          "target_meta": {"known": {"followers": 9000, "added": "2026-09-01T10:00+00:00"}}})
        self.patches = [unittest.mock.patch.object(targets, "STATE", self.state),
                        unittest.mock.patch.object(targets, "ITEMS", self.items),
                        unittest.mock.patch.object(targets.log_line, "__defaults__", (self.log,)),
                        unittest.mock.patch.object(targets, "_now", lambda: T0)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def write_state(self, d):
        self.state.write_text(json.dumps(d))

    def data(self):
        return json.loads(self.state.read_text())

    def logged(self):
        return [ln for ln in self.log.read_text().splitlines() if ln.startswith("- 2026")] if self.log.exists() else []

    def run_(self, *args, verdict=None):
        out, err = io.StringIO(), io.StringIO()
        fake = unittest.mock.patch.object(targets, "evaluate", lambda h, state: dict(verdict, handle=h)) if verdict \
            else unittest.mock.patch.object(targets, "run_verb", lambda args, timeout: self.fail("no x CLI in tests"))
        with fake, redirect_stdout(out), redirect_stderr(err):
            rc = targets.main(list(args))
        return rc, out.getvalue(), err.getvalue()

    def test_show(self):
        rc, out, _ = self.run_("show")
        self.assertEqual(rc, 0)
        self.assertIn("targets (1, mid-tier", out); self.assertIn("known", out); self.assertIn("bigvoice", out)
        self.assertEqual(self.data()["targets"], ["known"])                     # show never writes
        self.assertNotIn("updated", self.data())

    def test_show_without_a_state_file(self):
        self.state.unlink()
        rc, out, _ = self.run_("show")
        self.assertEqual(rc, 0); self.assertIn("targets (0,", out)

    def test_evaluate_rc_follows_eligibility(self):
        good = targets.verdict("newcomer", prof(), act(), {})
        rc, out, _ = self.run_("evaluate", "@newcomer", verdict=good)
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["handle"], "newcomer")                # @ stripped
        bad = targets.verdict("newcomer", prof("900"), act(), {})
        rc, out, _ = self.run_("evaluate", "newcomer", verdict=bad)
        self.assertEqual(rc, 3); self.assertFalse(json.loads(out)["eligible"])
        self.assertEqual(self.data()["targets"], ["known"])
        self.assertEqual(self.logged(), [])

    def test_add_already_a_target(self):
        rc, out, _ = self.run_("add", "@known", "--why", "again")
        self.assertEqual(rc, 0); self.assertIn("already a target", out)
        self.assertEqual(self.logged(), [])

    def test_add_not_eligible(self):
        bad = targets.verdict("newcomer", prof(bio="crypto signals daily"), act(), {})
        rc, out, err = self.run_("add", "newcomer", "--why", "seemed nice", verdict=bad)
        self.assertEqual(rc, 3); self.assertIn("not added", err); self.assertIn("exclusion", err)
        self.assertEqual(self.data()["targets"], ["known"])
        self.assertEqual(self.logged(), [])

    def test_add_list_full(self):
        many = ["acct%02d" % i for i in range(targets.LIST_MAX)]
        self.write_state({"targets": many, "megas": [], "target_meta": {}})
        good = targets.verdict("newcomer", prof(), act(), {})
        rc, _, err = self.run_("add", "newcomer", "--why", "why", verdict=good)
        self.assertEqual(rc, 3); self.assertIn("list is full", err)
        self.assertEqual(len(self.data()["targets"]), targets.LIST_MAX)

    def test_add_success(self):
        good = targets.verdict("newcomer", prof("12,5K"), act(9, 6), {})
        rc, out, _ = self.run_("add", "@newcomer", "--why", "answered me twice in a thread about evals", verdict=good)
        self.assertEqual(rc, 0); self.assertIn("added @newcomer (2 targets)", out)
        d = self.data()
        self.assertEqual(d["targets"], ["known", "newcomer"])
        meta = d["target_meta"]["newcomer"]
        self.assertEqual((meta["followers"], meta["replies_7d"], meta["distinct_7d"]), (12500, 9, 6))
        self.assertEqual(meta["added"], "2026-09-07T09:00+00:00")
        self.assertEqual(meta["why"], "answered me twice in a thread about evals")
        self.assertEqual(d["updated"], "2026-09-07T09:00+00:00")
        self.assertEqual(self.logged(), ["- 2026-09-07 09:00 + @newcomer (12500 followers, 9 replies/7d to 6 accounts) "
                                         "— answered me twice in a thread about evals"])

    def test_drop(self):
        rc, _, err = self.run_("drop", "stranger", "--why", "never was")
        self.assertEqual(rc, 2); self.assertIn("not a target", err)
        self.assertEqual(self.logged(), [])
        rc, out, _ = self.run_("drop", "@known", "--why", "went quiet")
        self.assertEqual(rc, 0); self.assertIn("dropped @known (0 targets)", out)
        d = self.data()
        self.assertEqual(d["targets"], [])
        self.assertEqual(d["target_meta"]["known"]["dropped"], "2026-09-07T09:00+00:00")
        self.assertEqual(d["target_meta"]["known"]["followers"], 9000)          # meta kept
        self.assertEqual(self.logged(), ["- 2026-09-07 09:00 - @known — went quiet"])

    def test_review_drops_and_saves(self):
        self.items.write_text(json.dumps({"items": [{"kind": "reply", "parent_handle": "known", "author_replied": None}] * 10}))
        rc, out, _ = self.run_("review")
        self.assertEqual(rc, 0); self.assertIn("DROP", out); self.assertIn("targets: 0 (plan wants", out)
        d = self.data()
        self.assertEqual(d["targets"], []); self.assertIn("dropped", d["target_meta"]["known"])
        self.assertEqual(len(self.logged()), 1); self.assertIn("@known: 10 of our replies", self.logged()[0])

    def test_review_without_items_file(self):
        rc, out, _ = self.run_("review")
        self.assertEqual(rc, 0); self.assertNotIn("DROP", out)
        self.assertEqual(self.data()["target_meta"]["known"]["our_replies"], 0)

    def test_mega_add_and_drop_are_idempotent(self):
        rc, out, _ = self.run_("mega", "add", "@loudone")
        self.assertEqual((rc, out.strip()), (0, "megas: 2"))
        rc, out, _ = self.run_("mega", "add", "loudone")
        self.assertEqual(out.strip(), "megas: 2")
        self.assertEqual(self.data()["megas"], ["bigvoice", "loudone"])
        rc, out, _ = self.run_("mega", "drop", "loudone")
        self.assertEqual(out.strip(), "megas: 1")
        rc, out, _ = self.run_("mega", "drop", "loudone")
        self.assertEqual(out.strip(), "megas: 1")
        self.assertEqual(self.data()["megas"], ["bigvoice"])
        self.assertEqual(self.logged(), ["- 2026-09-07 09:00 + mega @loudone", "- 2026-09-07 09:00 - mega @loudone"])


if __name__ == "__main__":
    unittest.main()
