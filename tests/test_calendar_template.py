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
        self.assertIn("calendarModel", content)
        self.assertIn("renderCalendar", content)
        self.assertIn("cal-count", content)
        self.assertIn("heat-", content)
        self.assertIn("calendar-tooltip", content)
        self.assertIn("calendar-agenda-list", content)
        self.assertIn("jumpToNextIssue", content)
        self.assertIn("keydown", content)
        self.assertIn("shiftKey", content)
        self.assertIn("ctrlKey", content)
        self.assertIn("URLSearchParams", content)
        self.assertIn("history.replaceState", content)
        self.assertIn("date=", content)
        self.assertIn("group=", content)
        self.assertIn("status=", content)

    def test_calendar_weekday_grid_and_dots(self):
        content = Path("checker.py").read_text(encoding="utf-8")
        self.assertIn("repeat(5,", content)
        self.assertIn("cal-dots-row", content)
        self.assertIn("weekdayHeaders", content)

    def test_calendar_group_slug_model(self):
        content = Path("checker.py").read_text(encoding="utf-8")
        self.assertIn("groupSlug", content)
        self.assertIn("groupSlugs", content)

    def test_calendar_skips_weekends(self):
        content = Path("checker.py").read_text(encoding="utf-8")
        self.assertIn("isWeekend", content)
        self.assertIn("skipWeekend", content)


if __name__ == "__main__":
    unittest.main()
