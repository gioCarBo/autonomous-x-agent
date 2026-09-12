"""caps.py: the CLI checks the daily ceilings before a write and consumes
them after evidence. validate_media: only render.py output may be attached."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xcli import caps, write  # noqa: E402

T0 = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)


class Caps(unittest.TestCase):
    def test_check_and_consume_roll_on_a_new_day(self):
        st = {"caps": {"date": "2000-01-01", "replies": 25, "likes": 30}}
        ok, detail = caps.check("reply", st, T0)
        self.assertTrue(ok); self.assertEqual(detail, "replies 1/25")
        self.assertEqual(st["caps"]["date"], "2026-09-06")
        self.assertEqual(caps.consume("like", st, T0), "likes 1/30")

    def test_ceilings(self):
        st = {"caps": {"date": "2026-09-06", "reposts": 2, "follows": 3, "likes": 29}}
        self.assertEqual(caps.check("repost", st, T0), (False, "reposts 2/2 today"))
        self.assertEqual(caps.check("follow", st, T0), (False, "follows 3/3 today"))
        self.assertEqual(caps.check("like", st, T0), (True, "likes 30/30"))

    def test_two_posts_per_hour(self):
        st = {"caps": {"date": "2026-09-06"}}
        for _ in range(2):
            self.assertTrue(caps.check("original", st, T0)[0])
            caps.consume("original", st, T0)
        ok, detail = caps.check("original", st, T0)
        self.assertFalse(ok); self.assertIn("2 posts in the last hour", detail)
        later = T0.replace(hour=13, minute=1)
        self.assertTrue(caps.check("original", st, later)[0])
        self.assertEqual(st["caps"]["originals"], 2)

    def test_persists_to_the_state_file(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "state.json"
            f.write_text(json.dumps({"targets": ["x"], "caps": {"date": "2026-09-06", "replies": 3}}))
            caps.consume("reply", None, T0, path=f)
            st = json.loads(f.read_text())
            self.assertEqual((st["caps"]["replies"], st["targets"]), (4, ["x"]))


class Media(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.renders = Path(self.tmp.name) / "renders"
        self.renders.mkdir()
        self._orig = write.RENDERS
        write.RENDERS = self.renders

    def tearDown(self):
        write.RENDERS = self._orig
        self.tmp.cleanup()

    def rendered(self, name="a.png", renderer="tools/render.py", data=b"\x89PNGok"):
        p = self.renders / name
        p.write_bytes(data)
        Path(str(p) + ".json").write_text(json.dumps({"renderer": renderer, "sha256": hashlib.sha256(data).hexdigest()}))
        return str(p)

    def test_rendered_image_passes(self):
        self.assertEqual(write.validate_media([self.rendered()]), [str(self.renders / "a.png")])
        self.assertEqual(write.validate_media(None), [])

    def test_outside_renders_is_refused(self):
        outside = Path(self.tmp.name) / "shot.png"; outside.write_bytes(b"x")
        with self.assertRaisesRegex(ValueError, "renders/"):
            write.validate_media([str(outside)])

    def test_missing_or_mismatched_sidecar(self):
        p = self.renders / "raw.png"; p.write_bytes(b"screenshot")
        with self.assertRaisesRegex(ValueError, "sidecar"):
            write.validate_media([str(p)])
        p2 = self.rendered("b.png")
        Path(p2).write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "does not match"):
            write.validate_media([p2])
        with self.assertRaisesRegex(ValueError, "does not match"):
            write.validate_media([self.rendered("c.png", renderer="hand")])

    def test_type_and_count(self):
        with self.assertRaisesRegex(ValueError, "unsupported"):
            write.validate_media([self.rendered("v.mp4")])
        five = [self.rendered("%d.png" % i) for i in range(5)]
        with self.assertRaisesRegex(ValueError, "at most 4"):
            write.validate_media(five)


if __name__ == "__main__":
    unittest.main()
