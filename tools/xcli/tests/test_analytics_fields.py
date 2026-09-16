"""`x analytics`: the Premium modal's localized labels map to stable keys,
unknown ones survive under `other`, counts parse like every other count."""

from __future__ import annotations

import json
import os
import sys
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xcli import read  # noqa: E402


class Fields(unittest.TestCase):
    def test_italian_ui_labels(self):
        raw = {"Visualizzazioni": "116", "Interazioni": "28", "Espansioni dettagli": "26",
               "Visite al profilo": "1"}
        self.assertEqual(read.analytics_fields(raw),
                         {"impressions": 116, "engagements": 28, "detail_expands": 26, "profile_visits": 1})

    def test_english_ui_and_thousands(self):
        raw = {"Impressions": "12.4K", "Engagements": "1,204", "Profile visits": "37", "New follows": "4"}
        self.assertEqual(read.analytics_fields(raw),
                         {"impressions": 12400, "engagements": 1204, "profile_visits": 37, "new_follows": 4})

    def test_unknown_label_is_kept_not_dropped(self):
        f = read.analytics_fields({"Visualizzazioni": "5", "Qualcosa di nuovo": "9"})
        self.assertEqual(f["impressions"], 5)
        self.assertEqual(f["other"], {"Qualcosa di nuovo": 9})

    def test_empty(self):
        self.assertEqual(read.analytics_fields({}), {})


class Verb(unittest.TestCase):
    class Cdp:
        def __init__(self, pages):
            self.pages, self.url = pages, None

        def goto(self, url, settle=3.0, max_wait=25.0):
            self.url = url

        def evaluate(self, js, timeout=30.0):
            sid = self.url.split("/status/")[1].split("/")[0]
            page = self.pages.get(sid)
            return json.dumps(page) if page else None

        def close(self):
            pass

    def test_multi_url_one_row_per_post(self):
        cdp = self.Cdp({"1": {"url": "https://x.com/GCBullGlasses/status/1",
                              "raw": {"Visualizzazioni": "116", "Visite al profilo": "1"}}})
        out = {}
        with unittest.mock.patch.object(read.session, "assert_owner_session", lambda c, a: "GCBullGlasses"), \
             unittest.mock.patch.object(read.envelope, "emit", lambda a, ev: out.update(ev)), \
             unittest.mock.patch.object(read.time, "sleep", lambda s: None):
            read.analytics(["https://x.com/GCBullGlasses/status/1", "https://x.com/i/status/2"], cdp=cdp)
        self.assertEqual(out["n"], 2)
        self.assertEqual(out["items"][0]["analytics"], {"impressions": 116, "profile_visits": 1})
        self.assertEqual(out["items"][1]["error"], "analytics-not-rendered")
        self.assertTrue(cdp.url.startswith("https://x.com/GCBullGlasses/status/2/analytics"))


if __name__ == "__main__":
    import unittest.mock  # noqa: F401
    unittest.main()
