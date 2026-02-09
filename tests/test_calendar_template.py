import unittest
from pathlib import Path


class TestCalendarTemplate(unittest.TestCase):
    def test_calendar_scaffold_ids(self):
        content = Path("checker.py").read_text(encoding="utf-8")
        self.assertIn("calendar-jump-today", content)
        self.assertIn("calendar-jump-issue", content)
        self.assertIn("calendar-view-toggle", content)
        self.assertIn("calendar-month-select", content)
        self.assertIn("calendar-agenda", content)
        self.assertIn("data-report-date", content)
        self.assertIn("data-date=\"", content)


if __name__ == "__main__":
    unittest.main()
