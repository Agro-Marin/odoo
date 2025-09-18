# Phase 2 Audit Report: Data Model & State Management

> **Date**: 2026-03-08
> **Auditor**: Claude Opus 4.6 (deep-audit agents, line-by-line)
> **Files audited**: 17 files across record lifecycle, save, commands, validation, preprocessing, x2many lists
> **Status**: Complete

---

## Severity Summary

| Severity | Count | Key Areas |
|----------|-------|-----------|
| **High** | 5 | preprocessor early return, urgentSave race, sendBeacon creation, record index mismatch, NaN sequences |
| **Medium** | 20 | dirty state leaks, preprocessor promises, undo x2many, sort stability, findIndex type mismatch |
| **Low** | 21 | JSDoc, naming, shadowing, edge cases |

## Fixes Applied

| # | File | Fix |
|---|------|-----|
| 1 | `record_preprocessors.js:212` | `return` → `continue` + `delete changes[fieldName]` |
| 2 | `record_save.js:61-65` | Guard sendBeacon: added `&& record.resId` |
| 3 | `record_save.js:84-86` | Merge `_changes` into `_values` before clearing after sendBeacon |
| 4 | `static_list_command_engine.js:264` | Match records by ID (`valuesById`) not array index |
| 5 | `command_builder.js:71` | Null-check `getRecord` result, `continue` on stale command |
| 6 | `record.js:303-304` | `resetFieldValidity` no longer sets `dirty = true` |
| 7 | `record_preprocessors.js:112` | Guard `completeMany2OneValue` falsy result |
| 8 | `static_list_sort.js:106-107` | Filter NaN/undefined sequences before `Math.min()` |
| 9 | `static_list_utils.js:28-33` | Normalize falsy values by field type in sort comparator |
| **Low** | 11 | JSDoc errors, input mutation, naming |

---

## HIGH FINDINGS

### 1. `preprocessPropertiesChanges` uses `return` instead of `continue` — data loss
**File**: `model/relational_model/record_preprocessors.js:212`

When a property belongs to a different parent, the function shows a warning and
calls `return;` inside the `for...of` loop. This exits the **entire function**,
not just the current iteration. Any subsequent fields (including non-property
fields) that haven't been processed yet are silently dropped from `changes`.

**Impact**: Saving a form with a mismatched property AND other changed fields
loses those other changes.

**Fix**: `return;` → `continue;` + `delete changes[fieldName]`

### 2. `urgentSave` bypasses the Mutex — race condition
**File**: `model/relational_model/record.js:326-347`

`urgentSave()` sets `_urgentSave = true`, triggers `WILL_SAVE_URGENTLY` (which
flushes UI changes via `update()` without the mutex), then calls `_save()` without
the mutex. If the async `_update()` from step 2 is still running (preprocessors,
`_applyChanges`), `_save()` may serialize incomplete `_changes`.

**Impact**: Corrupted save payload on page unload.

### 3. `sendBeacon` for record creation loses the new ID
**File**: `model/relational_model/record_save.js:76-86`

For new records (`!record.resId`), sendBeacon sends `web_save` but cannot receive
the response. The client clears `_changes` and sets `dirty = false` despite having
no confirmation the creation succeeded and no way to learn the new `resId`.

**Impact**: Record appears saved but `_values` has stale data. Next edit cycle
computes changes against wrong baseline.

**Fix**: Only use sendBeacon for existing records. For new records, fall through
to normal RPC or prevent page unload.

---

## MEDIUM FINDINGS

### 4. `setInvalidField` / `resetFieldValidity` dirty state leaks
**File**: `record.js:296-305`

`setInvalidField()` sets `dirty = true` before the `canProceed` check. If cancelled,
the record is dirty but no field was marked invalid. `resetFieldValidity()` also
unconditionally sets `dirty = true` — clearing a validation error shouldn't mark
the record as modified.

### 5. Preprocessor promises dropped during urgentSave
**File**: `record.js:986-1004`

Six preprocessors are launched via `Promise.all` but when `_urgentSave` is true,
the result is not awaited. Preprocessors write back into the `changes` object
asynchronously, so many2one fields may be saved with incomplete data.

### 6. `_getOnchangeValues` mutates `changes` argument in-place
**File**: `record.js:946-949`

Operation objects in `changes` are replaced in-place with computed values. If the
onchange RPC fails, the error handler calls `_applyChanges(changes)` with already-
mutated values, breaking the undo mechanism.

### 7. `_applyChanges` undo doesn't restore x2many StaticList state
**File**: `record.js:1029 + record.js:366-418`

The undo function restores `_changes`, `data`, and `_textValues` but not x2many
StaticList internals (`_commands`, `_currentIds`, `_cache`, `records`). If onchange
throws after x2many changes were applied, undo leaves the lists corrupted.

### 8. No-change save doesn't clear x2many StaticList commands
**File**: `record_save.js:56-58`

When a non-new record has no changes, `_changes` is cleared but x2many StaticLists
may still hold cancelled commands. `_clearCommands()` only happens in the `reload=false`
branch, not this early-return path.

### 9. `serializeCommands` crashes if record not in cache
**File**: `command_builder.js:70-82`

`getRecord(command[1])` can return `undefined` for stale commands referencing
deleted records. `getRecordChanges(undefined, ...)` then throws TypeError.

### 10. `applyCommands` matches loaded records by index, not by ID
**File**: `static_list_command_engine.js:260-273`

After `_loadRecords`, records are paired by array index with `recordsToLoad`. If
the server returns records in a different order (e.g., sorted by ID), data is
applied to the wrong Record datapoints.

**Fix**: `const data = recordValues.find(v => v.id === record.resId)`

### 11. `preprocessMany2OneReferenceChanges` crashes on falsy `completeMany2OneValue` result
**File**: `record_preprocessors.js:99-123`

When `completeMany2OneValue` returns `false`, the `.then()` callback destructures
`false` as `{id, display_name}` → TypeError.

### 12. Onchange coalescer: thrown `evaluateFn` leaves all resolvers pending
**File**: `onchange_coalescer.js:95-98`

If `evaluateFn` throws, the `for` loop resolving queued promises never runs. All
callers' Promises are permanently pending.

### 13. After sendBeacon save, `_values` not updated
**File**: `record_save.js:85-86 + record.js:70`

`_changes` is cleared but `_values` keeps old data. New edits compute changes
against stale `_values`, potentially generating duplicate/conflicting x2many commands.

### 14. `_applyValues` for x2many silently discards pending commands
**File**: `record.js:437-438`

When a record is reloaded with additional fields (e.g., `extendRecord`), x2many
`_changes` are overwritten with new StaticList instances, discarding any pending
commands without warning.

### 15. `record_validator.js:82-89` — empty object `{}` treated as "unset" for JSON fields
Required JSON fields with valid `{}` value fail validation because
`Object.keys(value).length === 0` is treated as empty.

---

## LOW FINDINGS

- `commands.js:21,27` — `create()`/`update()` mutate input `values` by deleting `id`
- `record.js:507-515` — JSDoc copy-paste error
- `record.js:62` — `_onUpdate` default no-op is `await`ed unnecessarily
- `record.js:372-374` — undo calls public `setInvalidField()` instead of `_invalidFields.add()`
- `record_value_transforms.js:48` — `properties` transform crashes on `false` value
- `record_validator.js:56-63` — `unsetRequiredFields` name conflates "unset" with "invalid children"
- `datapoint.js:23` — `markRaw()` mutates shared config
- `datapoint.js:47-51` — `fieldNames` getter recomputed on every access
- `onchange_coalescer.js:38-104` — coalescer appears to be dead code (never imported)
- `record_save.js:149-151` — `FetchRecordError` with potentially `false` resId
- `record_value_transforms.js:82-100` — `id` field default is `false` instead of `0`

---

## Prioritized Fix List

### Must Fix (High)
| # | File | Issue | Effort |
|---|------|-------|--------|
| 1 | record_preprocessors.js:212 | `return` → `continue` | Tiny |
| 2 | record_save.js:76-86 | Guard sendBeacon against creation | Small |
| 3 | record.js:326-347 | urgentSave mutex bypass race | Medium |

### Should Fix (Medium — top 5)
| # | File | Issue | Effort |
|---|------|-------|--------|
| 4 | static_list_command_engine.js:264 | Match records by ID not index | Small |
| 5 | record.js:300-305 | resetFieldValidity shouldn't set dirty | Tiny |
| 6 | record_preprocessors.js:99-123 | Guard completeMany2OneValue falsy result | Small |
| 7 | command_builder.js:70-82 | Null-check getRecord result | Small |
| 8 | record_save.js:85-86 | Merge _changes into _values after sendBeacon | Small |
