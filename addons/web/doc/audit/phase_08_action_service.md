# Phase 8 Audit Report: Action Service & Navigation

> **Date**: 2026-03-08
> **Files audited**: 7 files (action_service, action_container, action_dialog,
> action_state, action_info_builders, action_button_executor, breadcrumb_manager)
> **Findings**: 1 High, 14 Medium, 13 Low

---

## Fixes Applied

| # | File | Fix |
|---|------|-----|
| 1 | `action_button_executor.js:48` | Double-click prevention via `_executingButton` flag with try/finally |
| 2 | `action_service.js:1206` | `if (options.index)` → `if (options.index !== undefined)` to handle index=0 |
| 3 | `breadcrumb_manager.js:83` | Rejected breadcrumb cache entries are deleted (no permanent poisoning) |
| 4 | `action_state.js:91` | `JSON.parse` wrapped in try/catch for corrupted sessionStorage |

## Remaining Medium Issues (not yet fixed)

- `action_service.js:143-158` — RPC:RESPONSE handler mutates stack without coordination with `_updateUI`
- `action_service.js:300-304` — `_originalAction` stores full JSON per action (memory)
- `action_service.js:413-428` — `replacePreviousAction` fails silently for single-action stacks
- `action_service.js:937-942` — Function client action recursion has no depth limit
- `action_service.js:1073-1131` — `switchView` not guarded against concurrent calls
- `action_service.js:1167-1168` — Virtual controller restore truncates stack before doAction succeeds
- `action_button_executor.js:75-86` — `params.resIds` not defaulted to `[]`
- `action_state.js:100-107` — `active_id` not type-coerced from URL string
- `action_state.js:144-148` — `resId` not type-coerced from URL string
- `action_info_builders.js:82-86` — `group_by` empty string creates `[""]`
- `breadcrumb_manager.js:37-39` — Breadcrumb URL from stale `controller.state`
- `breadcrumb_manager.js:137-189` — Virtual controllers with empty `action: {}`
