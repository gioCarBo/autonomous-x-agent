"""items.py: one row per published item, snapshots tagged by the first
checkpoint they satisfy, collect is deterministic, report groups by field."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import items  # noqa: E402

T0 = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)


def url_at(when: datetime, n: int = 1) -> str:
    ms = int(when.timestamp() * 1000) - items.TWITTER_EPOCH_MS
    return "https://x.com/GCBullGlasses/status/%d" % ((ms << 22) + n)


def status_item(url, views, likes=0, replies=0):
    return {"url": url, "text": "hello", "metrics": {"views": views, "likes": likes, "reposts": 0, "replies": replies}}


def analytics_item(url, impressions, pv):
    return {"requested_url": url, "status_id": items.status_id(url),
            "analytics": {"impressions": impressions, "engagements": 3, "detail_expands": 2, "profile_visits": pv}}


NOW = datetime.now(timezone.utc)   # main() measures ages against the wall clock


def run_main(argv, stdin: str = "", env: dict | None = None):
    """Run the CLI in-process with a clean $X_AGENT_MODEL; returns (rc, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, env or {}), contextlib.redirect_stdout(out), \
            contextlib.redirect_stderr(err), mock.patch("sys.stdin", io.StringIO(stdin)):
        if not env:
            os.environ.pop("X_AGENT_MODEL", None)
        rc = items.main(argv)
    return rc, out.getvalue(), err.getvalue()


def envelope(evidence: dict) -> str:
    return json.dumps({"ok": True, "verb": "x", "evidence": evidence})


class Add(unittest.TestCase):
    def test_published_from_snowflake_and_upsert(self):
        d = items.load(items.Path("/nonexistent"))
        u = url_at(T0 - timedelta(minutes=30))
        it, created = items.add(d, u, now=T0, kind="original", series="take", model="glm-5.3-flash", followers=79)
        self.assertTrue(created)
        self.assertEqual(it["published"], "2026-09-06T11:30+00:00")
        it2, created2 = items.add(d, u, now=T0, series="metrics")
        self.assertFalse(created2)
        self.assertEqual(len(d["items"]), 1)
        self.assertEqual(it2["series"], "metrics")          # later tag wins
        self.assertEqual(it2["kind"], "original")           # default reply never downgrades
        self.assertEqual(it2["followers_at_publish"], 79)

    def test_parent_handle(self):
        d = items.load(items.Path("/nonexistent"))
        it, _ = items.add(d, url_at(T0), now=T0, parent="https://x.com/quietlantern/status/123")
        self.assertEqual(it["parent_handle"], "quietlantern")
        it2, _ = items.add(d, url_at(T0, 2), now=T0, parent="https://x.com/i/status/123")
        self.assertIsNone(it2["parent_handle"])

    def test_bad_url(self):
        with self.assertRaises(ValueError):
            items.add(items.load(items.Path("/nonexistent")), "https://x.com/quietlantern", now=T0)


class Checkpoints(unittest.TestCase):
    def setUp(self):
        self.d = items.load(items.Path("/nonexistent"))
        self.u = url_at(T0 - timedelta(minutes=60))
        items.add(self.d, self.u, now=T0)

    def test_due_and_tagging(self):
        it = self.d["items"][0]
        self.assertEqual(items.next_checkpoint(it, T0), "1h")
        self.assertEqual([x["url"] for x in items.due(self.d, T0)], [self.u])
        rep = items.record(self.d, now=T0, status_items=[status_item(self.u, 40, 2)],
                           analytics_items=[analytics_item(self.u, 45, 1)], followers=80)
        self.assertEqual(rep["touched"], 1)
        s = it["snapshots"][0]
        self.assertEqual((s["checkpoint"], s["age_min"], s["views"], s["likes"], s["impressions"], s["profile_visits"], s["followers"]),
                         ("1h", 60, 40, 2, 45, 1, 80))
        self.assertIsNone(items.next_checkpoint(it, T0))          # 1h done, 6h not yet
        self.assertEqual(items.due(self.d, T0), [])
        # nothing ran until t+30h: the 6h window was missed for good, 24h is due
        late = T0 + timedelta(hours=29)
        self.assertEqual(items.next_checkpoint(it, late), "24h")
        items.record(self.d, now=late, status_items=[status_item(self.u, 90)], analytics_items=[], followers=81)
        self.assertEqual(it["snapshots"][-1]["checkpoint"], "24h")
        self.assertEqual(it["snapshots"][-1]["age_min"], 30 * 60)
        self.assertIsNone(items._snap(it, "6h"))
        self.assertIsNone(items.next_checkpoint(it, late))
        # between windows nothing is due; a 19h-old backfilled post is not a "1h" reading
        gap = T0 + timedelta(hours=18)
        self.assertIsNone(items.next_checkpoint(it, gap))
        self.assertFalse(it["closed"])

    def test_72h_closes(self):
        it = self.d["items"][0]
        for h in (1, 6, 24, 72):
            now = T0 + timedelta(hours=h)
            items.record(self.d, now=now, status_items=[status_item(self.u, h)], analytics_items=[], followers=None)
        self.assertEqual([s["checkpoint"] for s in it["snapshots"]], ["1h", "6h", "24h", "72h"])
        self.assertTrue(it["closed"])
        self.assertEqual(items.due(self.d, T0 + timedelta(days=9)), [])

    def test_record_only_touches_requested_items(self):
        u2 = url_at(T0 - timedelta(minutes=90), 2)
        items.add(self.d, u2, now=T0)
        items.record(self.d, now=T0, status_items=[status_item(self.u, 1), status_item(u2, 2)],
                     analytics_items=[], followers=None, only={items.status_id(u2)})
        self.assertEqual(len(self.d["items"][0]["snapshots"]), 0)
        self.assertEqual(len(self.d["items"][1]["snapshots"]), 1)


class Collect(unittest.TestCase):
    def test_runs_profile_status_analytics_for_due_only(self):
        d = items.load(items.Path("/nonexistent"))
        fresh = url_at(T0 - timedelta(minutes=10), 1)
        old = url_at(T0 - timedelta(minutes=70), 2)
        items.add(d, fresh, now=T0); items.add(d, old, now=T0)
        calls = []

        def runner(args, timeout):
            calls.append(args)
            if args[0] == "profile":
                return {"counts": {"followers": "1.234", "following": "61"}}
            if args[0] == "status":
                return {"n": 1, "items": [status_item(old, 7)]}
            if args[0] == "analytics":
                return {"n": 1, "items": [analytics_item(old, 9, 2)]}
            return None

        rep = items.collect(d, now=T0, everything=False, runner=runner)
        self.assertEqual([c[0] for c in calls], ["profile", "status", "analytics"])
        self.assertEqual(calls[1][1:], [old])
        self.assertEqual((rep["due"], rep["touched"], rep["followers"]), (1, 1, 1234))
        self.assertEqual(d["items"][0]["snapshots"], [])
        self.assertEqual(d["items"][1]["snapshots"][0]["profile_visits"], 2)

    def test_nothing_due_runs_nothing(self):
        d = items.load(items.Path("/nonexistent"))
        items.add(d, url_at(T0 - timedelta(minutes=5)), now=T0)
        rep = items.collect(d, now=T0, everything=False, runner=lambda a, t: self.fail("ran %s" % a))
        self.assertEqual(rep["due"], 0)

    def test_verb_failure_is_partial_not_fatal(self):
        d = items.load(items.Path("/nonexistent"))
        old = url_at(T0 - timedelta(minutes=70))
        items.add(d, old, now=T0)

        def runner(args, timeout):
            return {"n": 1, "items": [status_item(old, 7)]} if args[0] == "status" else None

        rep = items.collect(d, now=T0, everything=False, runner=runner)
        self.assertEqual(rep["touched"], 1)
        s = d["items"][0]["snapshots"][0]
        self.assertEqual((s["views"], s.get("impressions"), s["followers"]), (7, None, None))


class ReadBack(unittest.TestCase):
    def test_report_groups_and_summary_lists(self):
        d = items.load(items.Path("/nonexistent"))
        for i, (series, model) in enumerate((("take", "flash"), ("take", "glm"), ("metrics", "flash"))):
            u = url_at(T0 - timedelta(hours=30, minutes=i), i + 1)
            items.add(d, u, now=T0, kind="original", series=series, model=model, followers=79)
            items.record(d, now=T0 - timedelta(hours=29, minutes=i), status_items=[status_item(u, 10 * (i + 1))],
                         analytics_items=[], followers=79, only={items.status_id(u)})
            items.record(d, now=T0 - timedelta(hours=5, minutes=i), status_items=[status_item(u, 100 * (i + 1))],
                         analytics_items=[analytics_item(u, 100 * (i + 1) + 5, i)], followers=80, only={items.status_id(u)})
        r = items.report(d, now=T0, days=14, by="series")
        self.assertIn("take", r); self.assertIn("metrics", r)
        take = [ln for ln in r.splitlines() if ln.startswith("take")][0]
        self.assertIn("  2 ", take)                # n
        self.assertIn(" 15 ", take)                # median v@1h of 10,20
        r2 = items.report(d, now=T0, days=14, by="model")
        self.assertIn("flash", r2); self.assertIn("glm", r2)
        s = items.summary(d, now=T0, hours=48)
        self.assertEqual(len(s.splitlines()), 5)
        self.assertIn("metrics", s)


class Backfill(unittest.TestCase):
    def test_imports_agent_rows_as_untagged_snapshots(self):
        d = items.load(items.Path("/nonexistent"))
        u = url_at(T0 - timedelta(days=1))
        stats = {"daily": [
            {"date": "2026-09-06", "followers": 79, "measured_at": "2026-09-06T10:00+00:00",
             "recent_posts": [{"url": u, "text": "t", "views": 50, "likes": 1, "reposts": 0, "replies": 0, "kind": "reply", "author": "agent"},
                              {"url": url_at(T0, 9), "text": "o", "views": 5, "kind": "reply", "author": "owner"}]},
            {"date": "2026-09-05", "followers": 76, "measured_at": "2026-09-05T20:00+00:00",
             "recent_posts": [{"url": u, "text": "t", "views": 20, "likes": 0, "reposts": 0, "replies": 0, "kind": "reply", "author": "agent"}]}]}
        n = items.backfill(d, stats, now=T0)
        self.assertEqual(n, 1)
        it = d["items"][0]
        self.assertTrue(it["backfilled"])
        self.assertEqual([s["views"] for s in it["snapshots"]], [20, 50])
        self.assertEqual([s["followers"] for s in it["snapshots"]], [76, 79])
        self.assertTrue(all(s["checkpoint"] is None for s in it["snapshots"]))
        self.assertEqual(items.backfill(d, stats, now=T0), 0)   # idempotent

    def test_readouts_add_the_rows_stats_lost(self):
        d = items.load(items.Path("/nonexistent"))
        u = url_at(T0 - timedelta(hours=20), 3)
        state = {"readouts": [
            {"url": u, "label": "mossfern-compaction", "opened": "2026-09-05T15:20+00:00", "status": "closed",
             "last": {"t": "2026-09-06T06:00+00:00", "views": 387, "likes": 2}},
            {"url": "https://x.com/i/status/notanid", "label": "junk"}]}
        self.assertEqual(items.backfill_readouts(d, state, now=T0), 1)
        it = d["items"][0]
        self.assertEqual((it["kind"], it["label"], it["snapshots"][0]["views"], it["snapshots"][0]["likes"]),
                         ("reply", "mossfern-compaction", 387, 2))
        self.assertEqual(items.backfill_readouts(d, state, now=T0), 0)


class Helpers(unittest.TestCase):
    def test_count_parses_the_profile_counter_strings(self):
        cases = ((None, None), (7, 7), ("61", 61), (" 80 ", 80), ("1.234", 1234), ("1,234", 1234),
                 ("1\xa0234", 1234), ("1,2K", 1200), ("1.2K", 1200), ("12k", 12000), ("2,5M", 2500000),
                 ("3M", 3000000), ("abc", None), ("", None), ("K", None))
        for raw, want in cases:
            with self.subTest(raw=raw):
                self.assertEqual(items._count(raw), want)

    def test_handle_from_parent_url(self):
        self.assertIsNone(items._handle(None))
        self.assertIsNone(items._handle(""))
        self.assertEqual(items._handle("https://x.com/quietlantern/status/1"), "quietlantern")
        self.assertEqual(items._handle("https://x.com/mossfern"), "mossfern")
        self.assertIsNone(items._handle("https://x.com/i/status/1"))      # anonymous permalink
        self.assertIsNone(items._handle("https://x.com/"))
        self.assertIsNone(items._handle("https://example.org/p/1"))

    def test_envelope_evidence_unwraps_or_passes_through(self):
        self.assertEqual(items._envelope_evidence(envelope({"url": "u", "text": "t"})), {"url": "u", "text": "t"})
        self.assertEqual(items._envelope_evidence('{"url": "u"}'), {"url": "u"})   # bare evidence
        self.assertEqual(items._envelope_evidence("[1, 2]"), {})
        self.assertEqual(items._envelope_evidence('"just a string"'), {})

    def test_find_by_url_id_query_string_and_tail(self):
        d = items.load(items.Path("/nonexistent"))
        sids = ("1700000000000001234", "1700000000000091234", "1700000000000000042")
        urls = ["https://x.com/GCBullGlasses/status/%s" % s for s in sids]
        for u in urls:
            items.add(d, u, now=T0)
        self.assertIs(items.find(d, urls[0]), d["items"][0])
        self.assertIs(items.find(d, sids[1]), d["items"][1])
        self.assertIs(items.find(d, urls[2] + "?s=20&t=abc"), d["items"][2])
        self.assertIs(items.find(d, "https://x.com/i/status/%s/photo/1" % sids[2]), d["items"][2])
        self.assertIs(items.find(d, "0042"), d["items"][2])                # unique tail
        self.assertIsNone(items.find(d, "1234"))                          # ambiguous tail
        self.assertIsNone(items.find(d, "9999"))
        self.assertIsNone(items.find(d, "nope"))                          # neither URL nor digits
        self.assertIsNone(items.find(d, "https://x.com/GCBullGlasses"))


class CollectRounds(unittest.TestCase):
    """collect() against a fake `x` runner returning the evidence dicts the CLI would."""

    def setUp(self):
        self.d = items.load(items.Path("/nonexistent"))
        self.calls = []

    def add_at(self, minutes: int, n: int) -> str:
        u = url_at(T0 - timedelta(minutes=minutes), n)
        items.add(self.d, u, now=T0)
        return u

    def runner_for(self, followers="1,2K", status=None, analytics=None):
        def runner(args, timeout):
            self.calls.append(list(args))
            self.assertIsInstance(timeout, (int, float))
            if args[0] == "profile":
                self.assertEqual(args[1:], [items.OWNER])
                return None if followers is None else {"counts": {"followers": followers, "following": "61"}}
            urls = args[1:]
            if args[0] == "status":
                return status(urls) if status else {"n": len(urls), "items": [status_item(u, 100) for u in urls]}
            if args[0] == "analytics":
                return analytics(urls) if analytics else {"n": len(urls), "items": [analytics_item(u, 130, 2) for u in urls]}
            self.fail("unexpected verb %s" % args)
        return runner

    def test_only_due_items_get_snapshots_tagged_by_window(self):
        in_window = [self.add_at(m, i + 1) for i, m in enumerate((70, 400, 1500, 5000))]
        fresh, between = self.add_at(10, 5), self.add_at(200, 6)
        rep = items.collect(self.d, now=T0, everything=False, runner=self.runner_for())
        self.assertEqual([c[0] for c in self.calls], ["profile", "status", "analytics"])
        self.assertEqual(self.calls[1][1:], in_window)
        self.assertEqual(self.calls[2][1:], in_window)
        self.assertEqual(set(rep), {"due", "touched", "closed", "followers"})
        self.assertEqual(rep, {"due": 4, "touched": 4, "closed": 1, "followers": 1200})
        labels = [it["snapshots"][0]["checkpoint"] for it in self.d["items"][:4]]
        self.assertEqual(labels, [c[0] for c in items.CHECKPOINTS])
        self.assertEqual([it["closed"] for it in self.d["items"][:4]], [False, False, False, True])
        for u in (fresh, between):
            self.assertEqual(items.find(self.d, u)["snapshots"], [])
        s = self.d["items"][0]["snapshots"][0]
        self.assertEqual((s["age_min"], s["views"], s["impressions"], s["profile_visits"], s["followers"]),
                         (70, 100, 130, 2, 1200))
        self.assertEqual(s["t"], items._iso(T0))
        # the round is idempotent within the same window: nothing due anymore
        self.calls.clear()
        rep2 = items.collect(self.d, now=T0, everything=False, runner=self.runner_for())
        self.assertEqual((rep2["due"], self.calls), (0, []))

    def test_errored_rows_produce_no_snapshot_and_none_profile_means_no_followers(self):
        u1, u2 = self.add_at(70, 1), self.add_at(80, 2)
        sid1 = items.status_id(u1)

        def status(urls):
            return {"n": 2, "items": [{"url": u1, "metrics": {"views": "120", "likes": 3, "replies": 0, "reposts": 1},
                                       "text": "measured text"},
                                      {"requested_url": u2, "error": "article-not-found"}]}

        def analytics(urls):
            return {"items": [{"status_id": sid1, "analytics": {"impressions": 130, "profile_visits": 2}},
                              {"requested_url": u2, "error": "article-not-found"}]}

        rep = items.collect(self.d, now=T0, everything=False, runner=self.runner_for(None, status, analytics))
        self.assertEqual(rep, {"due": 2, "touched": 1, "closed": 0, "followers": None})
        self.assertEqual(items.find(self.d, u2)["snapshots"], [])
        it1 = items.find(self.d, u1)
        s = it1["snapshots"][0]
        self.assertEqual((s["checkpoint"], s["views"], s["likes"], s["reposts"], s["impressions"], s["profile_visits"], s["followers"]),
                         ("1h", "120", 3, 1, 130, 2, None))
        self.assertNotIn("engagements", s)                    # analytics keys the round lacked stay absent
        self.assertEqual(it1["text"], "measured text")        # text filled from the reading when add had none

    def test_all_measures_every_open_item_even_between_windows(self):
        fresh, old = self.add_at(10, 1), self.add_at(70, 2)
        done = self.add_at(6000, 3)
        items.find(self.d, done)["closed"] = True
        rep = items.collect(self.d, now=T0, everything=True, runner=self.runner_for("79"))
        self.assertEqual(self.calls[1][1:], [fresh, old])
        self.assertEqual(rep, {"due": 2, "touched": 2, "closed": 0, "followers": 79})
        self.assertIsNone(items.find(self.d, fresh)["snapshots"][0]["checkpoint"])   # real age kept, no label
        self.assertEqual(items.find(self.d, fresh)["snapshots"][0]["age_min"], 10)
        self.assertEqual(items.find(self.d, old)["snapshots"][0]["checkpoint"], "1h")
        self.assertEqual(items.find(self.d, done)["snapshots"], [])

    def test_all_with_nothing_open_runs_nothing(self):
        items.find(self.d, self.add_at(70, 1))["closed"] = True
        rep = items.collect(self.d, now=T0, everything=True, runner=lambda a, t: self.fail("ran %s" % a))
        self.assertEqual(rep, {"touched": 0, "closed": 0, "followers": None, "due": 0})

    def test_single_url_status_envelope_without_items_is_recorded(self):
        self.add_at(70, 1)
        rep = items.collect(self.d, now=T0, everything=False,
                            runner=self.runner_for("80", status=lambda urls: status_item(urls[0], 33), analytics=lambda urls: None))
        self.assertEqual(rep, {"due": 1, "touched": 1, "closed": 0, "followers": 80})
        s = self.d["items"][0]["snapshots"][0]
        self.assertEqual((s["views"], s.get("impressions"), s["followers"]), (33, None, 80))

    def test_dry_run_lists_due_urls_and_runs_nothing(self):
        u = self.add_at(70, 1)
        self.add_at(10, 2)
        rep = items.collect(self.d, now=T0, everything=False, dry_run=True, runner=lambda a, t: self.fail("ran %s" % a))
        self.assertEqual(rep, {"due": 1, "urls": [u]})
        self.assertTrue(all(it["snapshots"] == [] for it in self.d["items"]))


class Readouts(unittest.TestCase):
    def test_label_kinds_and_snapshot_guards(self):
        d = items.load(items.Path("/nonexistent"))
        us = [url_at(T0 - timedelta(hours=20), n) for n in range(1, 7)]
        state = {"readouts": [
            {"url": us[0], "label": "diary-week-1", "note": "the diary post"},                 # no `last`: row only
            {"url": us[1], "label": "ab-second-original", "last": {"t": "2026-09-06T06:00+00:00", "views": 12, "likes": 1}},
            {"url": us[2], "label": "A/B variant", "last": {"t": "2026-09-06T06:00+00:00", "views": "12", "likes": 1}},   # views not int
            {"url": us[3], "label": "plain", "last": {"t": "yesterday", "views": 5}},                                 # bad time
            {"url": us[4], "label": "plain-2", "last": {"t": "2026-09-01T06:00+00:00", "views": 5}},                 # before publish
            {"url": "https://x.com/i/status/notanid", "label": "junk"},
            {"label": "no url at all"}]}
        self.assertEqual(items.backfill_readouts(d, state, now=T0), 5)
        kinds = {it["label"]: it["kind"] for it in d["items"]}
        self.assertEqual(kinds, {"diary-week-1": "original", "ab-second-original": "original", "A/B variant": "original",
                                 "plain": "reply", "plain-2": "reply"})
        self.assertEqual(items.find(d, us[0])["text"], "the diary post")
        self.assertEqual(items.find(d, us[2])["text"], "A/B variant")           # note missing: label is the text
        self.assertEqual([len(it["snapshots"]) for it in d["items"]], [0, 1, 0, 0, 0])
        s = items.find(d, us[1])["snapshots"][0]
        self.assertEqual((s["checkpoint"], s["views"], s["likes"], s["followers"]), (None, 12, 1, None))
        self.assertEqual(s["age_min"], 14 * 60)
        self.assertTrue(all(it["backfilled"] for it in d["items"]))
        self.assertEqual(items.backfill_readouts(d, state, now=T0), 0)
        self.assertEqual(items.backfill_readouts(d, {}, now=T0), 0)
        self.assertEqual(items.backfill_readouts(d, {"readouts": None}, now=T0), 0)

    def test_readout_for_a_known_item_adds_the_reading_only(self):
        d = items.load(items.Path("/nonexistent"))
        u = url_at(T0 - timedelta(hours=20), 1)
        items.add(d, u, now=T0, kind="original", series="take", text="my text")
        state = {"readouts": [{"url": u, "label": "diary", "last": {"t": "2026-09-06T06:00+00:00", "views": 40, "likes": 0}}]}
        self.assertEqual(items.backfill_readouts(d, state, now=T0), 0)
        it = d["items"][0]
        self.assertEqual((it["text"], it["series"], it.get("backfilled"), it.get("label")), ("my text", "take", None, None))
        self.assertEqual([s["views"] for s in it["snapshots"]], [40])
        # a second reading at another time sorts into place, the same time is skipped
        state["readouts"][0]["last"] = {"t": "2026-09-06T01:00+00:00", "views": 7}
        items.backfill_readouts(d, state, now=T0)
        items.backfill_readouts(d, state, now=T0)
        self.assertEqual([s["views"] for s in it["snapshots"]], [7, 40])


class Main(unittest.TestCase):
    """The CLI surface: every verb against a temp --file."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.file = self.dir / "items.json"
        self.argv = ["--file", str(self.file)]

    def write(self, name: str, text: str) -> str:
        p = self.dir / name
        p.write_text(text)
        return str(p)

    def seed(self, minutes: int = 70, n: int = 1, **kw) -> str:
        """Put one item published `minutes` ago straight into the file."""
        d = items.load(self.file)
        u = url_at(NOW - timedelta(minutes=minutes), n)
        items.add(d, u, now=NOW, **kw)
        items.save(self.file, d, NOW)
        return u

    def test_add_url_creates_then_updates(self):
        u = url_at(NOW - timedelta(minutes=5))
        rc, out, err = run_main(self.argv + ["add", u, "--kind", "original", "--series", "take", "--model", "lantern-9",
                                             "--followers", "79", "--wake", "2026-09-06-1500", "--text", "hello there"])
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(out.strip(), "item added …%s original take lantern-9" % items.status_id(u)[-8:])
        d = json.loads(self.file.read_text())
        self.assertEqual(len(d["items"]), 1)
        it = d["items"][0]
        self.assertEqual((it["kind"], it["series"], it["model"], it["followers_at_publish"], it["wake"], it["text"]),
                         ("original", "take", "lantern-9", 79, "2026-09-06-1500", "hello there"))
        self.assertIn("updated", d)
        rc, out, _ = run_main(self.argv + ["add", u, "--series", "metrics", "--parent", "https://x.com/quietlantern/status/9"])
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("item updated "))
        d = json.loads(self.file.read_text())
        self.assertEqual(len(d["items"]), 1)
        self.assertEqual((d["items"][0]["series"], d["items"][0]["kind"], d["items"][0]["parent_handle"]),
                         ("metrics", "original", "quietlantern"))

    def test_add_model_defaults_from_the_environment(self):
        u = url_at(NOW, 3)
        rc, out, _ = run_main(self.argv + ["add", u], env={"X_AGENT_MODEL": "fern-2"})
        self.assertEqual(rc, 0)
        self.assertTrue(out.strip().endswith(" reply fern-2"), out)
        rc, out, _ = run_main(self.argv + ["add", url_at(NOW, 4)])
        self.assertEqual(rc, 0)
        self.assertTrue(out.strip().endswith(" reply"), out)
        self.assertIsNone(json.loads(self.file.read_text())["items"][1]["model"])

    def test_add_from_envelope_file_and_stdin(self):
        u1, u2 = url_at(NOW, 1), url_at(NOW, 2)
        f = self.write("reply.json", envelope({"url": u1, "text": "from the envelope", "checked": False}))
        rc, out, err = run_main(self.argv + ["add", "--from-envelope", f, "--parent", "https://x.com/mossfern/status/5"])
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("item added "))
        rc, out, err = run_main(self.argv + ["add", "--from-envelope", "-", "--kind", "quote", "--text", "cli text wins"],
                                stdin=envelope({"url": u2, "text": "envelope text"}))
        self.assertEqual((rc, err), (0, ""))
        d = json.loads(self.file.read_text())
        self.assertEqual([(it["url"], it["text"], it["kind"], it["parent_handle"]) for it in d["items"]],
                         [(u1, "from the envelope", "reply", "mossfern"), (u2, "cli text wins", "quote", None)])
        # an explicit URL beats the envelope's
        u3 = url_at(NOW, 3)
        rc, _, _ = run_main(self.argv + ["add", u3, "--from-envelope", f])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(self.file.read_text())["items"][2]["url"], u3)

    def test_add_refuses_check_envelopes_bad_urls_and_nothing(self):
        f = self.write("check.json", envelope({"url": url_at(NOW), "text": "dry", "checked": True}))
        rc, out, err = run_main(self.argv + ["add", "--from-envelope", f])
        self.assertEqual((rc, out), (2, ""))
        self.assertIn("--check run", err)
        self.assertFalse(self.file.exists())
        rc, out, err = run_main(self.argv + ["add", "https://x.com/quietlantern"])
        self.assertEqual((rc, out), (2, ""))
        self.assertIn("not a status URL", err)
        rc, out, err = run_main(self.argv + ["add", "--from-envelope", "-"], stdin=json.dumps({"ok": False, "error": "boom"}))
        self.assertEqual((rc, out), (2, ""))
        self.assertIn("need a URL", err)
        rc, out, err = run_main(self.argv + ["add"])
        self.assertEqual((rc, out), (2, ""))
        self.assertIn("need a URL", err)
        self.assertFalse(self.file.exists())

    def test_collect_dry_run_and_patched_collect(self):
        u = self.seed(70, 1)
        self.seed(10, 2)
        before = self.file.read_bytes()
        rc, out, err = run_main(self.argv + ["collect", "--dry-run"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out), {"due": 1, "urls": [u]})
        self.assertIn("[items] collect: due=1 touched=0 closed=0 followers=None", err)
        self.assertEqual(self.file.read_bytes(), before)         # dry run never writes
        rc, out, _ = run_main(self.argv + ["collect", "--due", "--dry-run"])
        self.assertEqual((rc, json.loads(out)["due"]), (0, 1))

        seen = []

        def fake_collect(d, *, now, everything, dry_run=False, **kw):
            seen.append((everything, dry_run, sorted(kw)))
            if everything:
                for it in d["items"]:
                    it["snapshots"].append({"t": items._iso(now), "checkpoint": None, "views": 5})
                return {"touched": len(d["items"]), "closed": 0, "followers": 70, "due": len(d["items"])}
            return {"touched": 0, "closed": 0, "followers": 70, "due": 1}

        with mock.patch.object(items, "collect", fake_collect):
            rc, out, err = run_main(self.argv + ["collect"])
            self.assertEqual(rc, 0)
            self.assertEqual(seen, [(False, False, [])])
            self.assertEqual(self.file.read_bytes(), before)     # nothing touched: not rewritten
            self.assertIn("[items] collect: due=1 touched=0 closed=0 followers=70", err)
            rc, out, err = run_main(self.argv + ["collect", "--all"])
        self.assertEqual(rc, 0)
        self.assertEqual(seen[-1], (True, False, []))
        self.assertEqual(json.loads(out), {"touched": 2, "closed": 0, "followers": 70, "due": 2})
        self.assertIn("due=2 touched=2 closed=0 followers=70", err)
        d = json.loads(self.file.read_text())
        self.assertEqual([len(it["snapshots"]) for it in d["items"]], [1, 1])

    def test_collect_all_and_due_are_exclusive(self):
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stderr(io.StringIO()):
            items.main(self.argv + ["collect", "--due", "--all"])
        self.assertEqual(cm.exception.code, 2)

    def test_record_merges_saved_envelopes(self):
        u = self.seed(70, 1)
        st = self.write("status.json", envelope({"n": 1, "items": [status_item(u, 12, 1)]}))
        an = self.write("analytics.json", envelope({"n": 1, "items": [analytics_item(u, 15, 1)]}))
        rc, out, err = run_main(self.argv + ["record", "--status", st, "--analytics", an, "--followers", "80"])
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(json.loads(out), {"touched": 1, "closed": 0, "followers": 80})
        s = json.loads(self.file.read_text())["items"][0]["snapshots"][0]
        self.assertEqual((s["checkpoint"], s["views"], s["likes"], s["impressions"], s["profile_visits"], s["followers"]),
                         ("1h", 12, 1, 15, 1, 80))
        # a single-URL `x status` envelope carries the item itself, no `items`
        one = self.write("one.json", envelope(status_item(u, 44)))
        rc, out, _ = run_main(self.argv + ["record", "--status", one])
        self.assertEqual((rc, json.loads(out)), (0, {"touched": 1, "closed": 0, "followers": None}))
        snaps = json.loads(self.file.read_text())["items"][0]["snapshots"]
        self.assertEqual(([s["views"] for s in snaps], snaps[-1]["checkpoint"], snaps[-1]["followers"]), ([12, 44], None, None))
        # no envelopes at all: nothing to merge, still a valid round
        rc, out, _ = run_main(self.argv + ["record"])
        self.assertEqual((rc, json.loads(out)["touched"]), (0, 0))

    def test_mark_found_by_url_or_tail_and_not_found(self):
        u = self.seed(70, 1)
        sid = items.status_id(u)
        rc, out, err = run_main(self.argv + ["mark", u, "--author-replied"])
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(out.strip(), "…%s author_replied=True" % sid[-8:])
        self.assertIs(json.loads(self.file.read_text())["items"][0]["author_replied"], True)
        rc, out, _ = run_main(self.argv + ["mark", sid[-6:], "--no-author-replied"])
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "…%s author_replied=False" % sid[-8:])
        self.assertIs(json.loads(self.file.read_text())["items"][0]["author_replied"], False)
        before = self.file.read_bytes()
        rc, out, err = run_main(self.argv + ["mark", "https://x.com/i/status/1600000000000000000", "--author-replied"])
        self.assertEqual((rc, out), (2, ""))
        self.assertIn("no item for https://x.com/i/status/1600000000000000000", err)
        self.assertEqual(self.file.read_bytes(), before)
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            items.main(self.argv + ["mark", u])                      # one of the two flags is required

    def test_summary_and_report_by_each_field(self):
        u = self.seed(70, 1, kind="original", series="take", model="lantern-9")
        st = self.write("status.json", envelope({"items": [status_item(u, 12)]}))
        self.assertEqual(run_main(self.argv + ["record", "--status", st])[0], 0)
        rc, out, err = run_main(self.argv + ["summary"])
        self.assertEqual((rc, err), (0, ""))
        lines = out.splitlines()
        self.assertTrue(lines[0].startswith("items: 1 in 48h · 1 still measuring"), lines[0])
        self.assertEqual(len(lines), 3)
        self.assertIn("original take      lantern-9", lines[2])
        rc, out, _ = run_main(self.argv + ["summary", "--hours", "1"])
        self.assertEqual((rc, out.splitlines()), (0, ["items: 0 in 1h · 1 still measuring · next collect runs before the next wake"]))
        for by, key in (("series", "take"), ("model", "lantern-9"), ("kind", "original")):
            with self.subTest(by=by):
                rc, out, err = run_main(self.argv + ["report", "--by", by])
                self.assertEqual((rc, err), (0, ""))
                lines = out.splitlines()
                self.assertEqual(lines[0], "report 14d by %s: 1 items" % by)
                self.assertTrue(lines[1].startswith(by), lines[1])
                self.assertTrue(lines[2].startswith(key), lines[2])
                self.assertIn("  1     12      ·", lines[2])            # n, v@1h, v@24h
        rc, out, _ = run_main(self.argv + ["report", "--days", "0"])
        self.assertEqual((rc, out.splitlines()[0]), (0, "report 0d by series: 0 items"))
        rc, out, _ = run_main(self.argv + ["report"])
        self.assertEqual((rc, out.splitlines()[0]), (0, "report 14d by series: 1 items"))
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            items.main(self.argv + ["report", "--by", "wake"])

    def test_backfill_reads_patched_stats_and_state_files(self):
        u_stats = url_at(NOW - timedelta(days=1), 1)
        u_state = url_at(NOW - timedelta(hours=20), 2)
        day = (NOW - timedelta(hours=2)).isoformat(timespec="minutes")
        stats = {"daily": [{"date": day[:10], "followers": 79, "measured_at": day,
                            "recent_posts": [{"url": u_stats, "text": "t", "views": 50, "likes": 1, "reposts": 0, "replies": 0,
                                              "kind": "reply", "author": "agent"}]}]}
        state = {"readouts": [{"url": u_state, "label": "diary-3", "last": {"t": day, "views": 9, "likes": 0}}]}
        stats_p = self.dir / "stats.json"; state_p = self.dir / "state.json"
        stats_p.write_text(json.dumps(stats)); state_p.write_text(json.dumps(state))
        with mock.patch.object(items, "STATS_FILE", stats_p), mock.patch.object(items, "STATE_FILE", state_p):
            rc, out, err = run_main(self.argv + ["backfill"])
            self.assertEqual((rc, err), (0, ""))
            self.assertEqual(out.strip(), "backfilled 2 items (2 total)")
            d = json.loads(self.file.read_text())
            self.assertEqual([(it["url"], it["kind"], it["backfilled"], len(it["snapshots"])) for it in d["items"]],
                             [(u_stats, "reply", True, 1), (u_state, "original", True, 1)])
            self.assertEqual(d["items"][0]["snapshots"][0]["followers"], 79)
            self.assertEqual(d["items"][1]["label"], "diary-3")
            rc, out, _ = run_main(self.argv + ["backfill"])            # idempotent
            self.assertEqual((rc, out.strip()), (0, "backfilled 0 items (2 total)"))
        with mock.patch.object(items, "STATS_FILE", self.dir / "missing.json"), \
                mock.patch.object(items, "STATE_FILE", self.dir / "missing2.json"):
            rc, out, err = run_main(self.argv + ["backfill"])
        self.assertEqual((rc, err, out.strip()), (0, "", "backfilled 0 items (2 total)"))

    def test_no_verb_is_a_usage_error(self):
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stderr(io.StringIO()):
            items.main(self.argv)
        self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
