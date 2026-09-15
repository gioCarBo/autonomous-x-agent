"""Bug issues are deduplicated by exact title over the open list — not by
GitHub search, whose index lag and tokenizing opened #18 next to #17."""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xcli import failure  # noqa: E402

OPEN = json.dumps([{"number": 18, "title": "xcli: reply:no-modal"},
                   {"number": 17, "title": "xcli: reply:no-modal"},
                   {"number": 9, "title": "Tool generazione immagini"}])


class Dedup(unittest.TestCase):
    def test_finds_the_open_issue_by_exact_title(self):
        calls = []
        with patch.object(failure, "_gh", lambda a: (calls.append(a), (True, OPEN))[1]):
            url = failure._search_open_issue("reply:no-modal")
        self.assertTrue(url.endswith("/issues/18"))
        self.assertNotIn("--search", calls[0])
        self.assertIn("number,title", calls[0])

    def test_no_match_and_gh_failure_both_return_none(self):
        with patch.object(failure, "_gh", lambda a: (True, OPEN)):
            self.assertIsNone(failure._search_open_issue("reply:no-composer"))
        with patch.object(failure, "_gh", lambda a: (False, "gh: auth required")):
            self.assertIsNone(failure._search_open_issue("reply:no-modal"))
        with patch.object(failure, "_gh", lambda a: (True, "not json")):
            self.assertIsNone(failure._search_open_issue("reply:no-modal"))


if __name__ == "__main__":
    unittest.main()
