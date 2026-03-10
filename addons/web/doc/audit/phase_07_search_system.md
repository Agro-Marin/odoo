# Phase 7 Audit Report: Search System

> **Date**: 2026-03-08
> **Files audited**: 6 files (search_model, search_arch_parser, search_domain,
> search_bar, control_panel, search_panel)
> **Overall assessment**: Cleanest area audited — no critical or high findings.

---

## Fixes Applied

| # | File | Fix |
|---|------|-----|
| 1 | `search_bar.js:475` | Try/catch around `parseValue` in rapid-typing path |
| 2 | `search_panel.js:416` | Scope DOM query to `this.root.el` instead of `document` |

## Remaining Issues

### Medium
- `search_panel.js:415-431` — Now fixed. Was using `document.querySelectorAll` globally.

### Low
- `search_bar.js:396-398` — Spreading object into array for `subItems` is confusing.
- `search_query_mutations.js:195-208` — `nextId` increment after toggle is fragile ordering.
- `search_panel_state.js:248-249` — Domain comparison via `JSON.stringify` is fragile.
- `search_panel.js:302-312` — String/number type mismatch in `hasSelection`, masked by cast.
- `search_context.js:25` — Typo: `autocompleValue` missing 't'.

## Verified Correct
- **Domain AND/OR nesting** — items within a group OR'd, groups AND'd. Correct.
- **Favorite restore** — domain + groupBy + context + orderBy all properly saved/restored.
- **Date range timezone** — `serializeDateTime` converts to UTC, `DateTime.local()` for user TZ. Correct.
- **Autocomplete race conditions** — `KeepLast` properly guards against stale results.
- **Search panel category/filter domains** — correctly formed with `child_of` for hierarchical.
- **Comparison mode** — fully removed from codebase (no issues possible).
