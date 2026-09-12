"""mirror.py: blockers and do-not-reply handles become numbered placeholders, the
employer becomes "the owner's employer", private/old/rendered files stay home, and a
mirror that still holds a name or a secret is refused and removed.

Fixtures use invented names (blockerx, quietguy, Widgets Inc) and assemble every
token-shaped literal at runtime: this file is itself copied into the mirror and
grepped by verify()."""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mirror  # noqa: E402

PRIVATE = {"redact_handles": ["blockerx", "SecondBlocker"],
           "employer_terms": ["Widgets Inc"],
           "redact_terms": {"a PM at Widgets Inc": "a PM"}}
STATE = {"do_not_reply": {"quietguy": {"reason": "soft"}, "BlockerX": {"reason": "BLOCKED BY AUTHOR"}}}
AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"          # matches FORBIDDEN only once assembled
GH_TOKEN = "ghp" + "_" + "abcdefghij" * 3
EMPLOYER = "the owner's employer"


class RedactionMap(unittest.TestCase):
    def test_blockers_are_numbered_first_then_do_not_reply(self):
        handles, terms = mirror.redaction_map(PRIVATE, STATE)
        self.assertEqual(handles, {"blockerx": "[account-1]", "secondblocker": "[account-2]", "quietguy": "[account-3]"})

    def test_numbering_is_stable_when_do_not_reply_grows(self):
        before, _ = mirror.redaction_map(PRIVATE, STATE)
        grown = {"do_not_reply": {**STATE["do_not_reply"], "newguy": {}}}
        after, _ = mirror.redaction_map(PRIVATE, grown)
        for h, ph in before.items():
            self.assertEqual(after[h], ph)
        self.assertEqual(after["newguy"], "[account-4]")

    def test_a_handle_in_both_lists_gets_one_placeholder(self):
        handles, _ = mirror.redaction_map(PRIVATE, STATE)          # BlockerX is also a blocker
        self.assertEqual(len(handles), 3)
        self.assertEqual(len(set(handles.values())), 3)

    def test_employer_terms_default_and_redact_terms_pass_through(self):
        _, terms = mirror.redaction_map(PRIVATE, STATE)
        self.assertEqual(terms, {"a PM at Widgets Inc": "a PM", "Widgets Inc": EMPLOYER})
        _, custom = mirror.redaction_map({"employer_terms": ["Widgets Inc"], "redact_terms": {"Widgets Inc": "a fintech"}}, {})
        self.assertEqual(custom, {"Widgets Inc": "a fintech"})      # an explicit replacement wins over the default

    def test_missing_keys_and_null_do_not_reply(self):
        self.assertEqual(mirror.redaction_map({}, {}), ({}, {}))
        self.assertEqual(mirror.redaction_map({}, {"do_not_reply": None}), ({}, {}))


class Redact(unittest.TestCase):
    H = {"blockerx": "[account-1]", "quietguy": "[account-2]"}
    T = {"Widgets Inc": EMPLOYER}

    def test_case_insensitive_with_and_without_at(self):
        out = mirror.redact("cc @BlockerX and blockerx; QUIETGUY too", self.H, self.T)
        self.assertEqual(out, "cc [account-1] and [account-1]; [account-2] too")

    def test_word_boundaries_leave_prefixes_and_suffixes_alone(self):
        out = mirror.redact("blockerxyz myblockerx blockerx_2 blockerx.", self.H, self.T)
        self.assertEqual(out, "blockerxyz myblockerx blockerx_2 [account-1].")

    def test_terms_are_case_insensitive_whole_words(self):
        self.assertEqual(mirror.redact("we ship at widgets inc daily", self.H, self.T), "we ship at %s daily" % EMPLOYER)
        self.assertEqual(mirror.redact("Widgets Incorporated", self.H, self.T), "Widgets Incorporated")

    def test_longer_terms_and_handles_go_first(self):
        terms = {"Widgets": "W", "Widgets Inc": EMPLOYER}
        self.assertEqual(mirror.redact("Widgets Inc", {}, terms), EMPLOYER)     # not "W Inc"
        handles = {"blockerx": "[account-1]", "blockerx-labs": "[account-2]"}
        self.assertEqual(mirror.redact("@blockerx-labs vs @blockerx", handles, {}), "[account-2] vs [account-1]")

    def test_empty_maps_are_identity(self):
        self.assertEqual(mirror.redact("hello @blockerx", {}, {}), "hello @blockerx")


class Keep(unittest.TestCase):
    def test_never_paths_and_renders_are_excluded(self):
        for p in mirror.NEVER:
            self.assertFalse(mirror.keep(p, "2026-09-06"), p)
        self.assertFalse(mirror.keep("renders/2026-09-06-card.png", "2026-09-06"))

    def test_logs_before_the_cutoff_are_excluded(self):
        self.assertFalse(mirror.keep("logs/2026-09-05-wake.md", "2026-09-06"))
        self.assertTrue(mirror.keep("logs/2026-09-06-wake.md", "2026-09-06"))
        self.assertTrue(mirror.keep("logs/2026-09-07/notes.md", "2026-09-06"))
        self.assertFalse(mirror.keep("logs/README.md", "2026-09-06"))            # undated log: not proven recent

    def test_everything_else_is_kept(self):
        for p in ("README.md", "tools/mirror.py", "memory/state.json", "tools/tests/test_mirror.py", ".gitignore"):
            self.assertTrue(mirror.keep(p, "2026-09-06"), p)


class Verify(unittest.TestCase):
    H = {"blockerx": "[account-1]"}
    T = {"Widgets Inc": EMPLOYER}

    def tree(self, files: dict[str, str | bytes]) -> Path:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        for rel, body in files.items():
            p = tmp / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(body) if isinstance(body, bytes) else p.write_text(body)
        return tmp

    def test_leftover_handle_term_and_secret_are_reported(self):
        out = self.tree({"a.md": "said @BlockerX", "b/c.py": "# widgets inc", "d.txt": "key " + AWS_KEY, "e.md": GH_TOKEN})
        bad = mirror.verify(out, self.H, self.T)
        self.assertEqual(sorted(b.split(":")[0] for b in bad), ["a.md", "b/c.py", "d.txt", "e.md"])

    def test_clean_tree_returns_nothing(self):
        out = self.tree({"a.md": "said [account-1] of %s" % EMPLOYER, "b.py": "x = 1", "bin.dat": b"\xff\xfe\x00\x01"})
        self.assertEqual(mirror.verify(out, self.H, self.T), [])

    def test_git_dir_and_undecodable_files_are_skipped(self):
        out = self.tree({".git/config": "url = blockerx", "blob.bin": b"\xff\xfe blockerx"})
        self.assertEqual(mirror.verify(out, self.H, self.T), [])


class Build(unittest.TestCase):
    """A fake ROOT under a temp dir; tracked_files() is replaced by the list below."""
    TRACKED = ["README.md", "tools/mirror.py", "tools/agent.env", "memory/private.json", "memory/state.json",
               "renders/card.png", "logs/2026-09-05-old.md", "logs/2026-09-06-new.md", "data/blob.bin", "notes/odd.md"]
    BLOB = bytes(range(256))
    ODD = b"\xff\xfe not utf-8 \xe9"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.root, self.out = self.tmp / "root", self.tmp / "out"
        self.write("README.md", "@blockerx blocked us; quietguy said hi; we work at Widgets Inc\n")
        self.write("tools/mirror.py", "# the tool\n")
        self.write("tools/agent.env", "X_USER=owner\n")
        self.write("memory/private.json", json.dumps(PRIVATE))
        self.write("memory/state.json", json.dumps(STATE))
        self.write("renders/card.png", b"\x89PNG")
        self.write("logs/2026-09-05-old.md", "old log quoting @quietguy\n")
        self.write("logs/2026-09-06-new.md", "new log: BLOCKERX blocked\n")
        self.write("data/blob.bin", self.BLOB)
        self.write("notes/odd.md", self.ODD)
        for name, val in (("ROOT", self.root), ("PRIVATE", self.root / "memory" / "private.json"),
                          ("STATE", self.root / "memory" / "state.json"), ("tracked_files", lambda: list(self.TRACKED))):
            p = unittest.mock.patch.object(mirror, name, val)
            p.start(); self.addCleanup(p.stop)
        env = unittest.mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"})
        env.start(); self.addCleanup(env.stop)

    def write(self, rel: str, body: str | bytes):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body) if isinstance(body, bytes) else p.write_text(body)

    def build(self, push=None, logs_since="2026-09-06"):
        so, se = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
            rc = mirror.build(self.out, logs_since, push)
        return rc, so.getvalue(), se.getvalue()

    def git(self, *args) -> str:
        return subprocess.run(["git", "-C", str(self.out), *args], capture_output=True, text=True, check=True).stdout.strip()

    def test_refuses_without_private_json(self):
        (self.root / "memory" / "private.json").unlink()
        rc, _, err = self.build()
        self.assertEqual(rc, 2)
        self.assertIn("REFUSED", err)
        self.assertFalse(self.out.exists())

    def test_refuses_a_non_empty_out_dir(self):
        self.out.mkdir()
        (self.out / "stale").write_text("x")
        rc, _, err = self.build()
        self.assertEqual(rc, 2)
        self.assertIn("not empty", err)
        self.assertTrue((self.out / "stale").exists())                  # nothing touched

    def test_forbidden_pattern_after_redaction_removes_the_mirror(self):
        self.write("tools/mirror.py", "# leaked %s\n" % AWS_KEY)
        rc, _, err = self.build()
        self.assertEqual(rc, 3)
        self.assertIn("tools/mirror.py", err)
        self.assertFalse(self.out.exists())

    def test_leftover_handle_in_a_binary_named_text_file_is_caught(self):
        # redaction only runs on TEXT_EXT files; verify() still reads whatever decodes
        self.write("data/blob.bin", b"plain ascii mentioning blockerx")
        rc, _, err = self.build()
        self.assertEqual(rc, 3)
        self.assertIn("data/blob.bin", err)

    def test_clean_build_is_one_redacted_commit_on_main(self):
        calls = []
        real_run = subprocess.run

        def spy(argv, *a, **kw):
            calls.append(list(argv)); return real_run(argv, *a, **kw)
        with unittest.mock.patch.object(mirror.subprocess, "run", spy):
            rc, out, err = self.build()
        self.assertEqual(rc, 0, err)
        self.assertIn("6 files copied, 4 skipped, 3 handles and 2 terms redacted", out)
        self.assertEqual(self.git("rev-list", "--count", "HEAD"), "1")
        self.assertEqual(self.git("branch", "--show-current"), "main")
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual((self.out / "README.md").read_text(),
                         "[account-1] blocked us; [account-3] said hi; we work at %s\n" % EMPLOYER)
        self.assertEqual((self.out / "logs" / "2026-09-06-new.md").read_text(), "new log: [account-1] blocked\n")
        for gone in ("tools/agent.env", "memory/private.json", "renders", "logs/2026-09-05-old.md"):
            self.assertFalse((self.out / gone).exists(), gone)
        self.assertEqual((self.out / "data" / "blob.bin").read_bytes(), self.BLOB)          # non-text: byte copy
        self.assertEqual((self.out / "notes" / "odd.md").read_bytes(), self.ODD)            # undecodable text ext: byte copy
        self.assertEqual(mirror.verify(self.out, *mirror.redaction_map(PRIVATE, STATE)), [])
        self.assertFalse(any("push" in c or "remote" in c for c in calls))                # push=None: nothing leaves
        self.assertEqual(self.git("remote"), "")

    def test_logs_since_moves_the_cutoff(self):
        rc, out, _ = self.build(logs_since="2026-09-05")
        self.assertEqual(rc, 0)
        self.assertTrue((self.out / "logs" / "2026-09-05-old.md").exists())
        self.assertIn("7 files copied, 3 skipped", out)
        self.assertIn("history starts 2026-09-05", self.git("log", "-1", "--format=%s"))

    def test_push_is_a_force_push_of_main_to_origin(self):
        pushed = []
        real_run = subprocess.run

        def fake(argv, *a, **kw):
            if "push" in argv:
                pushed.append(list(argv)); return subprocess.CompletedProcess(argv, 0)
            return real_run(argv, *a, **kw)
        with unittest.mock.patch.object(mirror.subprocess, "run", fake):
            rc, out, _ = self.build(push="git@github-mirror:owner/public.git")
        self.assertEqual(rc, 0)
        self.assertEqual(pushed, [["git", "push", "-q", "--force", "origin", "main"]])
        self.assertEqual(self.git("remote", "get-url", "origin"), "git@github-mirror:owner/public.git")
        self.assertIn("force-pushed", out)


class Main(unittest.TestCase):
    def test_build_verb_forwards_out_cutoff_and_push(self):
        seen = []
        with unittest.mock.patch.object(mirror, "build", lambda out, since, push: seen.append((out, since, push)) or 0):
            self.assertEqual(mirror.main(["build", "/tmp/m"]), 0)
            self.assertEqual(mirror.main(["build", "/tmp/m", "--logs-since", "2026-09-01", "--push", "u"]), 0)
        self.assertEqual(seen, [(Path("/tmp/m"), "2026-09-06", None), (Path("/tmp/m"), "2026-09-01", "u")])

    def test_verb_is_required(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            mirror.main([])


if __name__ == "__main__":
    unittest.main()
