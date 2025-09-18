# Phase 13 Audit: List View + Form View (`views/list/`, `views/form/`)

**Scope**: 18 list view files (~5,827 lines), 14 form view files (~2,327 lines)
**Date**: 2026-03-07

---

## Files Audited

### List View (`views/list/`)
| File | Lines | Status |
|------|-------|--------|
| `list_renderer.js` | 1543 | Audited — 1 bug FIXED |
| `list_controller.js` | 561 | Audited — 1 bug FIXED |
| `list_arch_parser.js` | 343 | Audited — clean |
| `list_group_layout.js` | 132 | Audited — clean |
| `list_virtualization.js` | 231 | Audited — clean |
| `list_keyboard_nav.js` | 549 | Audited — clean |
| `list_keyboard_edit.js` | 345 | Audited — clean |
| `list_selection.js` | 219 | Audited — clean |
| `list_grid_state.js` | 458 | Audited — clean |
| `list_column_utils.js` | 81 | Audited — clean |
| `column_width_hook.js` | 473 | Audited — clean |
| `list_optional_fields.js` | 141 | Audited — clean |
| `list_aggregates.js` | 318 | Audited — 1 bug FIXED |
| `list_aggregates_row.js` | 179 | Audited — clean |
| `list_view.js` | 58 | Audited — clean |
| `list_cog_menu.js` | 22 | Audited — clean |
| `list_confirmation_dialog.js` | 134 | Audited — clean |
| `export_all/export_all.js` | 45 | Audited — clean |

### Form View (`views/form/`)
| File | Lines | Status |
|------|-------|--------|
| `form_controller.js` | 690 | Audited — 1 bug FIXED |
| `form_renderer.js` | 165 | Audited — clean |
| `form_compiler.js` | 760 | Audited — 1 bug FIXED |
| `form_arch_parser.js` | 73 | Audited — clean |
| `form_view.js` | 44 | Audited — clean |
| `form_label.js` | 76 | Audited — clean |
| `form_utils.js` | 124 | Audited — clean |
| `form_group/form_group.js` | 112 | Audited — clean |
| `form_cog_menu/form_cog_menu.js` | 9 | Audited — clean |
| `button_box/button_box.js` | 49 | Audited — clean |
| `status_bar_buttons/status_bar_buttons.js` | 28 | Audited — clean |
| `form_status_indicator/form_status_indicator.js` | 62 | Audited — clean |
| `form_error_dialog/form_error_dialog.js` | 61 | Audited — clean |
| `setting/setting.js` | 77 | Audited — clean |

---

## Bugs Found and Fixed

### BUG-1: [P2] getCellClass cache includes record-dependent condition (list_renderer.js:792-813)

**Category**: C-04 (caching correctness)
**Severity**: [P2] — Visible in edge cases during inline editing
**File**: `/home/marin/Odoo/core/addons/web/static/src/views/list/list_renderer.js`

**Problem**: The `getCellClass` method caches base CSS classes by `column.id`. However, the cached portion included a check `this.canUseFormatter(column, record)` which depends on the *record* (specifically whether it is in edition). If the first record to populate the cache for a given column happened to be the edited record, `canUseFormatter` returned `false`, and the column's `attrs.class` (e.g., `fw-bold`) was excluded from the cache. Since the cache was never invalidated, ALL subsequent records for that column would also miss the class for the entire component lifetime.

**Fix**: Removed the `canUseFormatter` guard from the cached portion. `column.attrs.class` is a static column property and should always be included in the base class list. The record-dependent decorations and display classes are already handled in the non-cached section below.

### BUG-2: [P2] Null-safety crash in onPageChangeScroll (list_controller.js:441)

**Category**: C-01 (null pointer)
**Severity**: [P2] — Crashes on pager navigation if DOM structure differs
**File**: `/home/marin/Odoo/core/addons/web/static/src/views/list/list_controller.js`

**Problem**: `this.rootRef.el.querySelector(".o_content .o_list_renderer").scrollTop = 0` — `querySelector` can return `null` if the DOM structure doesn't contain both `.o_content` and `.o_list_renderer` (e.g., during rapid pager navigation before the renderer is fully mounted, or in certain embedded list contexts). Accessing `.scrollTop` on `null` throws `TypeError`.

**Fix**: Added null check on the querySelector result before accessing `.scrollTop`.

### BUG-3: [P2] Null-safety crash in form autofocus effect (form_controller.js:267-269)

**Category**: C-01 (null pointer)
**Severity**: [P2] — Crashes if form view has no `.o_content` wrapper
**File**: `/home/marin/Odoo/core/addons/web/static/src/views/form/form_controller.js`

**Problem**: `this.rootRef.el.querySelector(".o_content").contains(document.activeElement)` — if `.o_content` is not present in the DOM (e.g., form rendered in certain dialog contexts without the standard layout), `querySelector` returns `null` and `.contains()` throws.

**Fix**: Changed to optional chaining: `.querySelector(".o_content")?.contains(...)`.

### BUG-4: [P3] for...in on array in multi-currency conversion (list_aggregates.js:200)

**Category**: C-03 (wrong iteration pattern)
**Severity**: [P3] — Works but fragile
**File**: `/home/marin/Odoo/core/addons/web/static/src/views/list/list_aggregates.js`

**Problem**: `for (const i in values)` iterates over array indices as strings and also iterates over any inherited enumerable properties. While functionally correct in practice (arrays rarely have extra enumerable properties), this is a known anti-pattern that can break if any library extends `Array.prototype`.

**Fix**: Changed to `for (let i = 0; i < values.length; i++)`.

### BUG-5: [P3] appendToExpr null input and lost non-expression content (form_compiler.js:33-37)

**Category**: C-02 (incorrect logic), M-01 (defensive coding)
**Severity**: [P3] — Only affects edge cases in custom compilers
**File**: `/home/marin/Odoo/core/addons/web/static/src/views/form/form_compiler.js`

**Problem**: `appendToExpr` received `null` when the element had no existing `t-attf-*` attribute (from `el.getAttribute(attrKey)`). The regex `exec(null)` coerces null to `"null"` string. Additionally, if `expr` contained static text (not wrapped in `{{ }}`), the regex wouldn't match and the static text was silently dropped, returning only the new expression.

**Fix**: Added early return for falsy `expr`, and in the non-match branch, preserved the existing `expr` before appending the new expression.

---

## Issues Noted (Not Fixed — Low Risk)

### NOTE-1: [P3] Missing `await` on recovery load in form pager (form_controller.js:454)

When a `FetchRecordError` is caught during pager navigation, the recovery `this.model.load(...)` call is fire-and-forget (not awaited). The error is re-thrown immediately after. While the intent is to surface the error to the user, the unawaited `load()` could fail silently or race with subsequent user actions.

### NOTE-2: [P3] ListCogMenu prop type mismatch (list_cog_menu.js:16)

`hasSelectedRecords` prop has `type: Number` but is semantically a boolean (used in truthy check). The actual value is `selection.length` (number) or a boolean from `isDomainSelected`. Works correctly but misleading to future maintainers.

### NOTE-3: [P3] Greedy regex in appendToExpr (form_compiler.js:34)

The regex `/{{.*}}/` uses greedy matching. If `expr` contained multiple `{{ }}` groups, it would match from the first `{{` to the last `}}`, collapsing intermediate content. In practice this isn't triggered because `appendToExpr` is only called once per element-attribute pair, but the regex should be non-greedy (`/{{.*?}}/`) for correctness.

---

## Architecture Assessment

### List View — Excellent Decomposition

The list view has been thoroughly decomposed into focused modules:
- **Navigation**: `list_keyboard_nav.js` + `list_keyboard_edit.js` — clean separation of read-only vs edit-mode keyboard handling
- **Selection**: `list_selection.js` — shift-range, long-touch, capture logic isolated
- **Virtualization**: `list_virtualization.js` — row virtualization with automatic threshold activation
- **Grid State**: `list_grid_state.js` — pure state object (no DOM, no OWL) for index-based navigation
- **Column Widths**: `column_width_hook.js` — complex resize/freeze logic well-encapsulated
- **Aggregates**: `list_aggregates.js` + `list_aggregates_row.js` — footer extraction into dedicated component

This architecture makes the 1543-line `list_renderer.js` manageable — it delegates to hooks rather than implementing everything inline.

### Form View — Clean Controller Pattern

The form view is well-structured:
- `form_controller.js` (690 lines) handles lifecycle cleanly: save, discard, pager, error recovery
- `form_compiler.js` (760 lines) is the most complex file but necessarily so — it transforms XML arch to OWL templates
- Sub-components (`button_box`, `status_bar_buttons`, `form_status_indicator`) are properly extracted

### Shared Strengths
- Consistent use of `@ts-check` and JSDoc
- No raw `this.state` mutation — proper `useState` reactivity
- Clean hook pattern (useListSelection, useListKeyboardNavigation, etc.)
- Proper event listener cleanup via OWL lifecycle hooks

---

## Summary

| Severity | Found | Fixed | Noted |
|----------|-------|-------|-------|
| [P1] | 0 | 0 | 0 |
| [P2] | 3 | 3 | 0 |
| [P3] | 2 | 2 | 3 |
| **Total** | **5** | **5** | **3** |

All 32 files across both views audited. The codebase is in good shape overall — the modular decomposition of the list view is particularly well done. The bugs found are edge-case null-safety issues and one caching correctness bug that could cause missing CSS classes during inline editing.
