# Calendar Upgrades Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the report calendar sticky, filter-aware, keyboard-navigable, and informative (counts/heat/tooltips), with agenda + URL persistence.

**Architecture:** Keep backend changes minimal. Build a client-side calendar model by scanning visible DOM rows after filters run, then render counts/heat/tooltips and agenda from that model. Persist state to URL and restore on load.

**Tech Stack:** Python (HTML string generation in `checker.py`), vanilla JS inlined in report HTML, CSS inlined in report HTML.

---

### Task 1: HTML/CSS scaffolding + data attributes

**Files:**
- Modify: `checker.py`
- Create: `tests/test_calendar_template.py`

**Step 1: Write the failing test**

Create `tests/test_calendar_template.py`:

```python
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
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_calendar_template.py -v`
Expected: FAIL with missing IDs/attributes.

**Step 3: Write minimal implementation**

Update `checker.py` to add:
- `reportDateIso` in the report model (YYYY-MM-DD) and render as `data-report-date` on the calendar container.
- `data-date`, `data-group-label`, and `data-group-url` attributes on each `.date-card`.
- New calendar controls in HTML:
  - Buttons: `#calendar-jump-today`, `#calendar-jump-issue`.
  - Toggle: `#calendar-view-toggle` (Month/Week).
  - Toggle: `#calendar-issues-only` (optional).
  - Toggle: `#calendar-search-toggle` (include search in calendar).
  - Month select: `#calendar-month-select`.
- Agenda container under calendar: `#calendar-agenda` with list + empty state.
- Sticky + collapsible calendar CSS (desktop sticky, mobile collapsed by default).

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_calendar_template.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add checker.py tests/test_calendar_template.py
git commit -m "feat: add calendar scaffold and data attributes"
```

---

### Task 2: Calendar model + counts/heat/tooltips

**Files:**
- Modify: `checker.py`
- Update: `tests/test_calendar_template.py`

**Step 1: Write the failing test**

Add new assertions in `tests/test_calendar_template.py`:

```python
self.assertIn("calendarModel", content)
self.assertIn("renderCalendar", content)
self.assertIn("cal-count", content)
self.assertIn("heat-", content)
self.assertIn("calendar-tooltip", content)
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_calendar_template.py -v`
Expected: FAIL (strings not present).

**Step 3: Write minimal implementation**

Update `checker.py` JS/CSS:
- Build `calendarModel` by scanning `.date-card` + visible rows after filters run.
- Compute counts by status (ok/bad/warn/date_mismatch/extra) and issue counts (missing + check + date_mismatch).
- Render per-day counts in calendar cells with `.cal-count`.
- Apply heat class `heat-0..4` based on issue count buckets.
- Add tooltips (`.calendar-tooltip` or `data-tip`) summarizing totals and top groups.
- Add “no events this month” state with a jump button to next month with events.
- Ensure `applyFilters()` calls calendar rebuild after DOM changes.

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_calendar_template.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add checker.py tests/test_calendar_template.py
git commit -m "feat: build calendar model with counts and heat"
```

---

### Task 3: Selection, agenda, navigation, keyboard

**Files:**
- Modify: `checker.py`
- Update: `tests/test_calendar_template.py`

**Step 1: Write the failing test**

Add assertions:

```python
self.assertIn("calendar-agenda-list", content)
self.assertIn("jumpToNextIssue", content)
self.assertIn("keydown", content)
self.assertIn("shiftKey", content)
self.assertIn("ctrlKey", content)
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_calendar_template.py -v`
Expected: FAIL.

**Step 3: Write minimal implementation**

Update `checker.py` JS/CSS:
- Default selection = report date or nearest upcoming event date.
- Click selects date; shift-click selects range; ctrl/cmd toggles multi-date.
- Agenda list under calendar: shows time/title/group/status; links to date-card anchors; quick actions (copy, open section, open source url if present).
- Jump buttons: today and next issue.
- Month jump select; week/month view toggle.
- Keyboard navigation: arrow keys move focus; Enter selects; `n`/`p` change month; `t` jump to today.
- Mobile collapse toggle: calendar collapses on small screens, agenda stays visible.

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_calendar_template.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add checker.py tests/test_calendar_template.py
git commit -m "feat: add calendar selection, agenda, and keyboard nav"
```

---

### Task 4: URL persistence + restore state

**Files:**
- Modify: `checker.py`
- Update: `tests/test_calendar_template.py`

**Step 1: Write the failing test**

Add assertions:

```python
self.assertIn("URLSearchParams", content)
self.assertIn("history.replaceState", content)
self.assertIn("date=", content)
self.assertIn("group=", content)
self.assertIn("status=", content)
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_calendar_template.py -v`
Expected: FAIL.

**Step 3: Write minimal implementation**

Update `checker.py` JS:
- Serialize filters + selection + view into URL params.
- On load, parse URL and restore filter controls + calendar state before rendering.
- Ensure calendar rebuilds after restore and `applyFilters()`.

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_calendar_template.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add checker.py tests/test_calendar_template.py
git commit -m "feat: persist calendar state in URL"
```

---

## Manual Verification Checklist
- Filters (status/group/category/search) update calendar counts/heat immediately.
- Jump to today/next issue works for both month and week views.
- Shift-click range and ctrl/cmd multi-select update agenda and totals.
- URL params restore state on reload.
- Sticky calendar works on desktop; collapsed calendar works on mobile.
- No-events month shows message and jump control.

