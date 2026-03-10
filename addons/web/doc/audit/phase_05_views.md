# Phase 5 Audit Report: View System

> **Date**: 2026-03-08
> **Files audited**: 11 files (form controller/renderer/compiler, list controller/renderer,
> view base/compiler/utils)
> **Status**: Form + List complete. Kanban/Calendar/Pivot pending.

---

## Fixes Applied

| # | File | Fix |
|---|------|-----|
| 1 | `form_controller.js:471` | `beforeLeave`: use `await isDirty()` instead of synchronous `dirty` check |
| 2 | `form_status_indicator.js:25-36` | Move `useRef` before `useEffect` + null guard on `saveButton.el` |
| 3 | `view_compiler.js:233,239` | Fix typo: `isVisileExpr` → `isVisibleExpr` |

## Remaining Issues

### High
- `record_save.js:61-101` — sendBeacon payload limit (~64KB) with no field-level fallback.
  Large binary/HTML fields easily exceed this. When beacon fails, browser's generic
  "unsaved changes" dialog is shown but modern browsers ignore custom messages.

### Medium
- `form_controller.js:464-467` — `beforeVisibilityChange` auto-save swallows all errors
  silently via `.catch(() => {})`. User never learns their auto-save failed.
- `form_controller.js:464-467` — Visibility-change save doesn't check `isNew`.
  New records with incomplete required fields silently fail.
- `list_renderer.js:1092-1097` — Record index may be stale after resequence. Should
  look up by `resId` instead of array index.
- `list_renderer.js:1116-1118` — `leaveEditMode` not awaited before `openRecord`.
- `form_controller.js:194-203` — Footer extraction mutates `archInfo.xmlDoc` in place
  via `.append()` which moves DOM nodes.
- `form_status_indicator.js:46-52` — `indicatorMode` conflates "new" and "dirty" states.

### Low
- `view_compiler.js:437-446` — `validateNode` warns on forbidden directives but doesn't
  prevent compilation. OWL may process them unexpectedly.
- `view_compiler.js:478-489` — Template cache key includes full `outerHTML` (can be large).
- `form_compiler.js:37-39` — `appendToExpr` regex `{{.*}}` is greedy, may lose prefix
  with multiple interpolation blocks.
- `list_renderer.js:242-284` — Performance marks on every render (should gate behind debug).
