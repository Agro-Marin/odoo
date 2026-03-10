# Phase 5B Audit Report: Kanban, Calendar, Pivot Views

> **Date**: 2026-03-08
> **Files audited**: 10 files across kanban (controller, renderer, record, compiler),
> calendar (controller, model, renderer), pivot (model, renderer)
> **Overall assessment**: Relatively clean — 1 medium, 9 low

---

## Fixes Applied

| # | File | Fix |
|---|------|-----|
| 1 | `calendar_model.js:442` | `dateStartType` → `dateStopType` for date_stop serialization |
| 2 | `pivot_renderer.js:351` | Extract view ID from tuple: `?.find(...)?.[0]` instead of whole tuple |

## Remaining Issues

### Low (most impactful)
- `dynamic_group_list.js:112` — `moveRecord` not mutex-protected. Concurrent drags
  can corrupt group record lists. Should wrap in `model.mutex.exec()`.
- `kanban_controller.js:196,205` — Missing null checks on `querySelector` results
  during scroll restore.
- `calendar_common_renderer.js:393-396` — Day-scale all-day events not adjusted for
  end-exclusive dates (off-by-one on resize).

## Verified Correct
- **Kanban drag-drop**: resequence + group-change commands generated correctly.
- **Calendar timezone**: UTC ↔ local conversion via Luxon is correct.
- **Calendar DST**: handled transparently by Luxon's IANA timezone database.
- **Pivot row/column intersection**: `[rowValues, colValues]` key composition correct.
- **Pivot drill-down**: parent context maintained via `groupDomains` lookup.
- **Pivot flip**: correctly swaps trees and twists all key pairs.
- **Pivot concurrency**: double protection via `race` + `keepLast`.
