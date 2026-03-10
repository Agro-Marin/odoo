# Phase 14 — views/ kanban + calendar Audit Output

**Scope**: `static/src/views/kanban/` (16 files) + `static/src/views/calendar/` (20 files)
**File count**: 36
**Status**: COMPLETE — 2 P1, 3 P2 fixed; 5 notes documented

---

## Fixed Findings

### `kanban/progress_bar_hook.js:208` — [P1] C-03 — Null deref on `aggregateField.type`

**Problem**: `aggregateField` can be `false` when no aggregate is configured. Accessing `.type`
on `false` throws TypeError. Crashes progress bar rendering for kanban views without aggregates.
**Fix**: Added `aggregateField &&` guard.

---

### `kanban/kanban_record_quick_create.js:223-225` — [P1] C-08 — Direct mutation of shared props context

**Problem**: `this.props.context.default_name = values.name` mutated the shared context object,
polluting it for all subsequent quick-creates and other consumers of the same context.
**Fix**: Spread into new object: `const context = { ...this.props.context, default_name: ... }`.

---

### `calendar/calendar_record.js:59` — [P2] C-01 — Day-of-month comparison instead of full date

**Problem**: `start.day === end.day` only compares 1-31. An event spanning Jan 1 to Feb 1
incorrectly treated as same-day. **Fix**: `start.hasSame(end, "day")`.

---

### `calendar/calendar_model.js:367` — [P2] C-02 — Array always truthy

**Problem**: `if (filterIds)` always true for arrays (even `[]`), sending useless
`orm.write(model, [], ...)` RPC. **Fix**: `if (filterIds.length)`.

---

### `kanban/kanban_controller.js:204` — [P2] C-05 — Unquoted data-id in CSS selector

**Problem**: `data-id=${id}` without quotes crashes querySelector for IDs with special chars.
**Fix**: Added quotes around the attribute value.

---

## Documented (Not Fixed)

| Sev | Location | Description |
|-----|----------|-------------|
| P3 | progress_bar_hook.js:324 | Variable `group` shadows outer scope |
| P3 | kanban_controller.js:205 | Missing null check on querySelector result |
| P3 | kanban_renderer.js | toggleRangeSelection crash if record deleted between clicks |
| P3 | calendar_date_range.js | No lower-bound domain when date_delay used without date_stop |
| P3 | calendar_model.js | buildRawRecord uses dateStartType for date_stop serialization |
