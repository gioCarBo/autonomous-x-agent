"""`x replies`: conversation pairs and "Replying to @x" rows count as answers
to other accounts; self-replies and old rows do not."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xcli import read  # noqa: E402

NOW = 1_800_000_000_000


def sid(age_days: float) -> str:
    return str((NOW - int(age_days * 86400000) - read.TWITTER_EPOCH_MS) << 22)


def row(author, age_days, ctx=None):
    return {"url": f"https://x.com/{author}/status/{sid(age_days)}", "author": author, "ctx": ctx}


class Activity(unittest.TestCase):
    def test_pairs_context_and_window(self):
        rows = [row("[account-5]", 0.1),                                  # own post
                row("[account-5]", 0.2, "In risposta a [account-5]"),          # self-thread: no
                row("Ian", 0.3), row("[account-5]", 0.3),                  # pair: yes
                row("xSoli", 0.5), row("[account-5]", 0.5),                # pair: yes
                row("[account-5]", 0.6, "Replying to @ryatkins"),          # context: yes
                row("old", 9), row("[account-5]", 9)]                      # older than 7d: no
        a = read.reply_activity(rows, "[account-5]", NOW)
        self.assertEqual((a["replies_to_others"], a["distinct_accounts"], a["rows"]), (3, 3, 9))

    def test_case_insensitive_handle(self):
        rows = [row("Ian", 0.3), row("[account-5]", 0.3)]
        self.assertEqual(read.reply_activity(rows, "[account-5]", NOW)["replies_to_others"], 1)


if __name__ == "__main__":
    unittest.main()
