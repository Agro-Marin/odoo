# Phase 6 Audit Report: Field Widgets

> **Date**: 2026-03-08
> **Files audited**: 13 files (formatters, parsers, many2one, x2many, float, char, html,
> datetime, field_tooltip, standard_field_props, supporting utilities)

---

## Fixes Applied

| # | File | Fix |
|---|------|-----|
| 1 | `formatters.js:256` | `formatInteger`: type guard for non-number/non-finite values |
| 2 | `formatters.js:299` | `formatX2many`: null guard for falsy `value` |
| 3 | `x2many_field.js:303` | `switchToForm`: guard `newRecordIndex === -1`, fallback to last |

## Remaining Issues

### High (flagged, not fixed — requires design decision)
- `html_field.xml:6` — `t-out` renders raw HTML without client-side sanitization.
  XSS risk when field has `sanitize=False` or data bypasses ORM write.
  The `web_editor` module provides proper WYSIWYG with sanitization, but this
  base `web` fallback has none. Fix requires adding DOMPurify dependency or
  restricting `t-out` usage.

### Medium
- `parsers.js:73` — `parseNumber` with empty `thousandsSep` creates degenerate regex
  (functional but wasteful).
- `html_field.js:8-10` — Asymmetric edit (plain text textarea) vs readonly (raw HTML)
  experience. Base widget is intentionally thin fallback for web_editor.

### Low
- `formatters.js:34` — `humanSize(0)` returns `""` instead of `"0 Bytes"`.
- `formatters.js:72` — Unbounded `booleanCheckboxId` counter.
- `field_tooltip.js:12` — Null dereference if `fieldInfo.field` is undefined.
- `many2one.js:30-31` — `extractData` crashes if `record.name` is `false`.
- `float_field.js:46` — `formattedValue` returns raw `false` when `formatNumber` disabled.
- `x2many_field.js:197-206` — Fragile pager offset adjustment after abandoned new record.
- `operation.js:27` — Division by zero in Operation returns `Infinity`.

### Round-Trip Correctness (Verified OK)
- `parseFloat(formatFloat(value))` — correct for all tested cases
- `parseInteger(formatInteger(value))` — correct with INT32 bounds check
- `parsePercentage(formatPercentage(value))` — correct (expected precision loss from formatting)
- `parseMonetary(formatCurrency(value))` — correct with currency digits
- Currency decimal_places (JPY=0, USD=2, KWD=3) — correctly threaded
