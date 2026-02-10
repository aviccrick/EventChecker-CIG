import sys
import types
import unittest

# Stub external deps so checker.py can import without installing packages.
fake_requests = types.ModuleType("requests")
fake_bs4 = types.ModuleType("bs4")
class _DummySoup:  # pragma: no cover - test stub
    pass
fake_bs4.BeautifulSoup = _DummySoup

fake_playwright = types.ModuleType("playwright")
fake_sync_api = types.ModuleType("playwright.sync_api")
class _DummyTimeout(Exception):
    pass

def _dummy_sync_playwright():
    raise RuntimeError("not used in tests")

fake_sync_api.sync_playwright = _dummy_sync_playwright
fake_sync_api.TimeoutError = _DummyTimeout

sys.modules.setdefault("requests", fake_requests)
sys.modules.setdefault("bs4", fake_bs4)
sys.modules.setdefault("playwright", fake_playwright)
sys.modules.setdefault("playwright.sync_api", fake_sync_api)

import checker


class CalendarReportTests(unittest.TestCase):
    def test_calendar_scaffold_and_js_present(self):
        report = {
            "generated_friendly": "Today",
            "sourceLastUpdatedFriendly": "Now",
            "nextUpdateMsg": "",
            "nextUpdateDue": False,
            "nextUpdateTargetEpoch": None,
            "priority": [],
            "groups": [
                {
                    "display": "Cancer",
                    "url": "https://example.com",
                    "sections": [
                        {
                            "date_iso": "2026-02-02",
                            "date_uk": "02/02/2026",
                            "category": "Internal",
                            "title": "Interest group seminar",
                            "rows": [],
                            "any_mismatch": False,
                            "has_missing": False,
                            "has_date_mismatch": False,
                            "missing": [],
                            "date_mismatches": [],
                            "extras": [],
                            "likely_pairs": [],
                            "source_label": "CrickNet",
                        }
                    ],
                }
            ],
        }

        html = checker.render_report_html(report)
        self.assertIn('id="calendar-card"', html)
        self.assertIn('id="calendar-grid"', html)
        self.assertIn('id="calendar-events-list"', html)
        self.assertIn('id="calendar-events-empty"', html)
        self.assertIn('filterDate(todayStr)', html)
        self.assertIn('renderCalendarMonth()', html)


if __name__ == "__main__":
    unittest.main()
