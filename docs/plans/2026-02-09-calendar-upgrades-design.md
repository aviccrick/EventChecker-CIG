# Calendar Upgrades Design

## Goal
Upgrade the report calendar to be informative, filter-aware, and navigable with agenda, keyboard shortcuts, and URL persistence, while keeping backend changes minimal.

## Context
The calendar is rendered inside `checker.py` with inline CSS/HTML/JS. It currently uses `window.CALENDAR_EVENTS` (per date + group) and displays dots only. Filters in `applyFilters()` toggle visibility of rows and date cards by updating the DOM.

## Architecture (DOM-Driven, Minimal Backend Changes)
- Build the calendar model by scanning the visible DOM after `applyFilters()` runs.
- Use visible rows (`tbody tr` that are not hidden) to compute per-date counts by status.
- Calendar cells render counts (total + Missing/Check emphasis), heat shading, and tooltips.
- Agenda is generated from visible DOM rows and links to date-card anchors.
- URL persistence mirrors filter + calendar state; on load, parse URL and restore state before rendering.

This approach guarantees calendar parity with active filters (group, status, category, optional search) without refactoring server-side report generation.

## Data Model (Client-Side)
`calendarState`:
- `view`: "month" or "week"
- `currentMonth`: Date (month being rendered)
- `focusDate`: ISO date string used for navigation
- `selectedDates`: Set of ISO date strings
- `issuesOnly`: boolean (show only days with Missing/Check)
- `includeSearch`: boolean (whether search filter affects calendar)

`calendarModel` (derived on each rebuild):
- `byDate`: Map ISO date -> { total, ok, missing, check, extra, dateMismatch, issues, groups: Map<group, count>, agenda: [items] }
- `issueDates`: sorted list of dates where issues > 0
- `eventDates`: sorted list of dates with any events

Agenda item structure:
- `date`, `group`, `category`, `status`, `title`, `time` (if present), `anchor`, `sourceUrl` (if present)

## Default Selection Logic
- Determine `reportDateIso` from a new `data-report-date` attribute injected into the HTML (YYYY-MM-DD).
- Select the earliest visible event date that is on/after `reportDateIso`.
- If none exist, fall back to nearest prior event date; if none exist, fall back to today.

## Calendar Cell Rendering
For each visible date:
- Show day number, total count, and Missing/Check emphasis (e.g., "12 | 3 M / 2 C").
- Apply heat shading based on `issues = missing + check + dateMismatch` (bucketed 0..N).
- Show tooltip: "OK / Missing / Check / Extra totals" plus top groups by issue count.
- Maintain selected/today styles with higher specificity than heat styles.

## Interaction & Navigation
- **Click**: select date, update agenda, and scroll to the first matching date-card section.
- **Shift-click**: select range from `focusDate` to clicked date; agenda shows combined totals.
- **Ctrl/Cmd-click**: toggle multi-date selection.
- **Keyboard**: arrow keys move focus; Enter selects focus date; `n`/`p` month next/prev; `t` jump to today.
- **Jump to Today**: sets focus + selection to today and scrolls if present.
- **Jump to Next Issue**: jumps to the next date (>= focus date) with Missing/Check under current filters.

## Filters & Search
- Calendar rebuilds after `applyFilters()` and uses only visible rows and visible date cards.
- Add a toggle "Include search in calendar" (default on desktop, optional on mobile) to control whether `filterSearch` affects calendar counts.

## Month/Week Views
- Month view: full grid for `currentMonth`.
- Week view: 7-day row starting Monday for the week containing `focusDate`.
- Toggle between views; month label shows "Feb 2026" in month view and "Week of 2026-02-09" in week view.

## Sticky + Responsive Behavior
- On desktop, the calendar card is sticky within the left column (`position: sticky; top: 1rem; align-self: start;`).
- Ensure parent containers do not set `overflow` that disables sticky.
- On narrow screens, calendar becomes a collapsible bar (default collapsed) with agenda visible below.

## Empty States
- If no events in the rendered month/week, show a clear message and a button to jump to the next month that has events.

## Error Handling / Edge Cases
- If no matching dates for selection, show agenda empty state and disable jump buttons.
- If `reportDateIso` is missing or invalid, fall back to today.
- If no events at all, disable calendar navigation actions that depend on events.

## Testing Strategy
- Manual verification in generated report HTML:
  - Filters (status/group/category/search) immediately update calendar counts and heat.
  - Jump to today/next issue works for both month and week views.
  - Range selection and multi-select update agenda and totals.
  - URL params restore state on reload.
  - Sticky behavior remains effective (no parent overflow regression).
  - Mobile collapsible calendar shows agenda properly.

## Implementation Notes (Touchpoints)
- `checker.py`:
  - Inject `data-report-date` into the HTML root or calendar container.
  - Add HTML controls (jump buttons, view toggle, issues-only toggle, include-search toggle, month jump).
  - Extend CSS for counts, heat shading, tooltips, agenda list, and responsive collapse.
  - Extend JS: rebuild calendar model after `applyFilters()`; render calendar cells from model; add keyboard and URL persistence.

