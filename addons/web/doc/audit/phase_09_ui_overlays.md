# Phase 9 Audit Report: UI Overlay System

> **Date**: 2026-03-08
> **Files audited**: ~20 files across dialog, notification, overlay, popover,
> tooltip, block UI, effects, bottom sheet
> **Findings**: 3 High, 8 Medium, 8 Low

---

## Fixes Applied

| # | File | Fix |
|---|------|-----|
| 1 | `block_ui.js:82` | `setTimeout` → `browser.setTimeout` (test harness compatibility) |
| 2 | `notification.js:82-98` | Cancel rAF on destroy/freeze via `_rafHandle` tracking |
| 3 | `notification.js:62-65` | `freeze()` cancels rAF + null guard on `autocloseProgress.el` |
| 4 | `bottom_sheet.js:155-166` | Re-enable `isSnappingEnabled` after `updateDimensions()` |
| 5 | `popover.js:254` | Add rejection handler to `animation.finished.then()` |

## Remaining Issues

### High (flagged)
- `notification.xml` / `rainbow_man.xml` — `t-out` renders content as raw HTML.
  Intentional for markup support but callers must sanitize. Same pattern as
  the HTML field XSS concern from Phase 6.

### Medium
- `bottom_sheet.js:329,xml:18` — Props `onBack` and `preventDismissOnContentScroll`
  used but not declared in `static props`. OWL validation rejects them.
- `bottom_sheet.js:83` — `history.pushState` on every sheet open disrupts history.
- `tooltip.js` — `JSON.parse` of tooltip data attributes without try/catch.
- `block_ui.js` — Message shown for first block, not for subsequent blocks.

### Low
- `bottom_sheet.js:248` — Scroll listener never removed on destroy.
- `ui_service.js:115` — Focus restore on detached element is no-op (focus lost).
- `notification.js` — Multiple `startNotificationTimer` calls without stopping previous.

### Verified Correct
- Dialog close always unblocks UI (overlay service cleanup is thorough).
- Escape key closes topmost dialog only (active element tracking correct).
- Overlay z-index stacking via DOM order + sequence sorting is correct.
- Focus trap correctly handles Tab/Shift+Tab cycling.
- Rainbow man cleanup after animation is correct (useEffect return).
