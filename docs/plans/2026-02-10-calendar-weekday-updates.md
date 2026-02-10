# Calendar Weekday Updates Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Update the report calendar to be weekday-only, fit the sidebar, use group dots instead of counts, stop auto-scroll on date click, remove agenda copy actions, and add a full-section collapse toggle.

**Architecture:** Keep the calendar in `checker.py` with inline CSS/HTML/JS. Extend the calendar model to track per-date group slugs for dot rendering, adjust rendering to 5-column weekdays, and update selection logic to skip weekends. Adjust agenda rendering and collapse behavior in the same JS block.

**Tech Stack:** Python (HTML template assembly), inline CSS, inline JS.

### Task 1: Add weekday-only grid + dot indicators scaffolding tests

**Files:**
- Modify: `tests/test_calendar_template.py`

**Step 1: Write the failing test**

```python
    def test_calendar_weekday_grid_and_dots(self):
        content = Path("checker.py").read_text(encoding="utf-8")
        self.assertIn("repeat(5,", content)
        self.assertIn("cal-dots-row", content)
        self.assertIn("weekdayHeaders", content)
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_calendar_template.py -v`
Expected: FAIL with missing `repeat(5,` / `cal-dots-row` / `weekdayHeaders`.

**Step 3: Write minimal implementation**

Add a `weekdayHeaders` array and update the calendar grid rendering + CSS to 5 columns. Add dot row markup and CSS class usage in the calendar cell renderer.

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_calendar_template.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add tests/test_calendar_template.py checker.py
git commit -m "test: add weekday calendar scaffolding assertions"
```

### Task 2: Extend calendar model for group dots + fix group label escaping

**Files:**
- Modify: `checker.py`
- Test: `tests/test_calendar_template.py` (already updated)

**Step 1: Write the failing test**

```python
    def test_calendar_group_slug_model(self):
        content = Path("checker.py").read_text(encoding="utf-8")
        self.assertIn("groupSlug", content)
        self.assertIn("groupSlugs", content)
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_calendar_template.py -v`
Expected: FAIL with missing `groupSlug` / `groupSlugs`.

**Step 3: Write minimal implementation**

- In the date-card template, add `data-group-slug="{slug}"`.
- In `buildCalendarModel()`, read `groupSlug` from the card and store in agenda items.
- Add a `groupSlugs` Set per date; use it for dot rendering.
- Avoid double-escaping group label in `data-group-label` by using the raw name (not an already escaped string) before HTML escaping.

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_calendar_template.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add checker.py tests/test_calendar_template.py
git commit -m "feat: track group slugs for calendar dots"
```

### Task 3: Render weekday-only dates and skip weekends in selection

**Files:**
- Modify: `checker.py`

**Step 1: Write the failing test**

```python
    def test_calendar_skips_weekends(self):
        content = Path("checker.py").read_text(encoding="utf-8")
        self.assertIn("isWeekend", content)
        self.assertIn("skipWeekend", content)
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_calendar_template.py -v`
Expected: FAIL with missing `isWeekend` / `skipWeekend`.

**Step 3: Write minimal implementation**

- Add `isWeekend(dateObj)` helper.
- In `renderCalendar()`, only push weekday dates to `renderDates`.
- Update `buildDateRange()` and `moveFocusBy()` to skip weekends.
- Update week view to generate only Mon–Fri.

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_calendar_template.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add checker.py tests/test_calendar_template.py
git commit -m "feat: render calendar weekdays only"
```

### Task 4: Remove date auto-scroll + remove agenda copy button

**Files:**
- Modify: `checker.py`

**Step 1: Write the failing test**

```python
    def test_calendar_no_copy_action(self):
        content = Path("checker.py").read_text(encoding="utf-8")
        self.assertNotIn("Copy", content)
        self.assertNotIn("navigator.clipboard", content)
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_calendar_template.py -v`
Expected: FAIL because Copy button is still present.

**Step 3: Write minimal implementation**

- Remove the copy button block from agenda rendering.
- Update `handleDateClick()` to stop calling `scrollToDate()`.

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_calendar_template.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add checker.py tests/test_calendar_template.py
git commit -m "feat: remove agenda copy action and date auto-scroll"
```

### Task 5: Collapse toggle hides entire calendar section + fix overflow

**Files:**
- Modify: `checker.py`

**Step 1: Write the failing test**

```python
    def test_calendar_collapse_all_sizes(self):
        content = Path("checker.py").read_text(encoding="utf-8")
        self.assertIn("calendar-body", content)
        self.assertIn("is-collapsed", content)
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_calendar_template.py -v`
Expected: FAIL with missing `calendar-body`.

**Step 3: Write minimal implementation**

- Wrap controls + wrapper + agenda in a `div#calendar-body`.
- Update collapse CSS to hide `#calendar-body` at all breakpoints when collapsed.
- Keep collapse toggle visible at all sizes.
- Ensure grid/cells use `min-width: 0` and `grid-template-columns: repeat(5, minmax(0, 1fr))` to prevent overflow.

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_calendar_template.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add checker.py tests/test_calendar_template.py
git commit -m "feat: collapse full calendar section and prevent overflow"
```

### Task 6: Full test run

**Files:**
- Test: `tests/`

**Step 1: Run full tests**

Run: `python -m unittest -v`
Expected: All tests pass (note: baseline failure for `filterDate(todayStr)` is known; verify it is still the only failure).

**Step 2: Commit (if needed)**

```bash
git add checker.py tests/test_calendar_template.py
git commit -m "test: verify calendar updates"
```
