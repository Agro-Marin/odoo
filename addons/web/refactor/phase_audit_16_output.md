# Phase 16 — webclient/ Audit Output

**Scope**: `static/src/webclient/` — 45 files, ~6,384 lines
**Status**: COMPLETE — 2 P1, 3 P2 fixed

---

## Fixed Findings

### `actions/reports/report_hook.js:59-60` — [P1] C-02 — view-id string instead of number in doAction

**Problem**: `getAttribute("view-id")` returns a string, passed into `views` array where
the server expects `number | false`. String view IDs cause type mismatches in action resolution.
**Fix**: `Number(viewIdAttr)` when present, `false` when absent.

---

### `actions/action_button_executor.js` — [P1] C-09 — UI permanently blocked on doAction throw

**Problem**: When `block-ui="true"` and `doAction` throws, `ui.unblock()` was never reached,
permanently freezing the UI with the block overlay.
**Fix**: Wrapped in `try/finally` to guarantee `ui.unblock()`.

---

### `actions/breadcrumb_manager.js` — [P2] C-01 — Misaligned controllers with RPC results

**Problem**: `loadBreadcrumbs` skipped menu/client-action controllers from the keys array
but not from the controllers array, causing `zip()` to misalign breadcrumb labels with
the wrong action.
**Fix**: Track controller-key pairs together.

---

### `actions/action_service.js` — [P2] C-02 — `"null"` string stored in sessionStorage

**Problem**: `_openActionInNewWindow` stored `null` as the string `"null"` when no prior
action existed, causing subsequent reads to parse `"null"` as a valid action.
**Fix**: Use `removeItem()` for null values.

---

### `actions/action_state.js:178` — [P2] C-03 — Recursive getActionParams null deref

**Problem**: `getActionParams()` can return `null` on invalid URL state, but line 181
accessed `params.options` without guard.
**Fix**: Added `if (!params) return null;` guard.

---

## Files with No Findings

All remaining 40 files in webclient/ (actions/ infrastructure, debug/, clickbot/, menus/,
navbar/, user_menu/, switch_company_menu/) were clean.
