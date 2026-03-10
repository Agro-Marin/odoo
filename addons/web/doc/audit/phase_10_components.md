# Phase 10 Audit Report: Components Library

> **Date**: 2026-03-08
> **Files audited**: 10+ files (dropdown, datetime_picker, autocomplete, pager,
> notebook, domain_selector, record_selector, file_input)
> **Findings**: 2 High, 11 Medium, 17 Low

---

## Fixes Applied

| # | File | Fix |
|---|------|-----|
| 1 | `datetime_picker.js:580` | Clamp hour+1 to 23 to prevent midnight wrap |
| 2 | `datetime_picker.js:582-583` | `\|\|` → `??` for minute/second defaulting |
| 3 | `autocomplete.js:313-352` | Loop guard `maxIterations` prevents infinite loop on all-unselectable options |
| 4 | `notebook.js:119` | Null guard on `pages.find()` result |
| 5 | `file_input.js:101-114` | try/finally ensures `isDisable` is reset on upload error |

## Remaining Issues

### High (flagged)
- `datetime_picker_service.js:85-148` — Event listeners on inputs never removed.
  The returned cleanup function is a no-op. `listenedElements` WeakSet prevents
  double-add but not cleanup. Needs architectural fix.

### Medium
- `dropdown.js:377-381` — `_focusedElBeforeOpen` captured after popover opens.
- `datetime_picker_service.js:148` — Anonymous click listener on calendar icon can't be removed.
- `datetime_picker_service.js:196` — `getInput(0).parentElement` null crash.
- `autocomplete.js:100-116` — `pendingPromise` can be orphaned by rapid typing.
- `autocomplete.xml:28` — `role="menu"` should be `role="listbox"` (ARIA).
- `pager.js:125-128` — Negative offset wrapping formula confusing.
- `pager.js:164-171` — Rapid clicks race between `isDisabled` guard.
- `notebook.js:168-170` — `splice` with index inserts at wrong position for multiple indexed pages.
- `domain_selector.js:93-103` — Mutating `tree.children` in-place breaks cacheability.
- `file_input.js:52` — Multi-file upload only checks first file size.
