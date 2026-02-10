# Calendar Weekday Updates Design

**Goal:** Fix calendar overflow and agenda label issues, remove weekend rendering, replace count text with group dots, disable auto-scroll on date click, remove agenda copy buttons, and add a full-section collapse toggle.

**Context:** The calendar is rendered inside `checker.py` with inline CSS/HTML/JS. It builds a client-side `calendarModel` by scanning visible `.date-card` rows and renders cells, tooltips, and agenda items from that model.

## Requirements
- Calendar grid should render **Monday–Friday only** (no Saturday/Sunday cells).
- The calendar should fit within the sidebar (no overflow).
- Date cells should show **colored dots for interest groups** scheduled that day instead of `0M 1C` counts.
- Clicking a date should **only update the agenda** (no scroll to date section). Jump buttons can still scroll.
- Agenda should not show HTML-escaped group labels (e.g., `&amp;`).
- Remove the agenda **Copy** button.
- Add a **min/max accordion toggle** that collapses the **entire calendar section** (controls, grid, events, agenda) on all screen sizes.

## Approach
### Calendar rendering
- Change the calendar grid to **5 columns** with headers `M T W T F`.
- Render only weekday dates in month/week views.
- Ensure sizing does not overflow the sidebar by using `grid-template-columns: repeat(5, minmax(0, 1fr))` and `min-width: 0` on grid items.

### Date indicators
- Replace the count block with a dot row.
- Track unique group slugs per date and render a dot for each, using `.group-{slug}` to reuse `--group-color`.

### Agenda behavior
- Remove the **Copy** action button from each agenda entry.
- Ensure agenda group labels use the raw group name (no double-escaping).
- Keep the “Open” and optional “Source” buttons.

### Click behavior
- Date selection should **not** auto-scroll to the date card. This means removing the `scrollToDate()` call from standard date clicks (keep for jump actions).
- Keep agenda updates and event pill filtering on date selection.

### Collapse behavior
- Make the collapse toggle visible at all breakpoints.
- Collapse should hide the entire calendar section (controls, grid, events, agenda), not just the grid.

## Data flow adjustments
- Extend agenda items to include `groupSlug` for dot rendering.
- Track `groupSlugs` per date in `calendarModel.byDate`.

## Testing
- Update `tests/test_calendar_template.py` to assert:
  - Weekday-only headers and 5-column grid usage.
  - Presence of dot row markup for date cells.
  - Collapse toggle in calendar header still present.

## Risks
- Weekday-only rendering changes date range logic; ensure range selection and keyboard navigation skip weekends.
- Ensure dots remain readable in dense schedules (may need a max-dot cap later if cluttered).
