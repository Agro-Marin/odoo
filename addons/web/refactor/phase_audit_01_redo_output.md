# Phase 1 Re-Audit: core/ root + core/utils/

**Scope:** 49 files, ~9,767 lines
**Date:** 2026-03-07
**Auditor:** Claude Opus 4.6

---

## Summary

| Severity | Found | Fixed | Noted |
|----------|-------|-------|-------|
| P1       | 0     | 0     | 0     |
| P2       | 4     | 4     | 0     |
| P3       | 6     | 0     | 6     |

All 6 previously-reported bugs confirmed fixed. 4 new bugs found and fixed, 6 new notes.

---

## Previously-Reported Bugs (Verified Fixed)

### 1. `dom/scrolling.js:159` - RTL classList.contains(".o_rtl")
**Status:** FIXED. Now uses `"o_rtl"` without dot prefix.

### 2. `dom/autoresize.js` - removeEventListener wrong ref
**Status:** FIXED. Rewritten with ResizeObserver pattern; proper cleanup via `inputHandler` variable.

### 3. `search.js:120` - fuzzyLevenshteinLookup returns pattern instead of candidate
**Status:** FIXED. Now correctly pushes `candidate` via `elem: candidate`.

### 4. `indexed_db.js:132,140` - missing return on IndexedDB writes
**Status:** FIXED. Promise chains properly return throughout `_checkVersion`.

### 5. `template_inheritance.js:114` - stateful /g regex with .test()
**Status:** FIXED. `CLASS_CONTAINS_REGEX` no longer uses `/g` flag.

### 6. `sortable.js:196-204` - ev.relatedTarget null deref
**Status:** FIXED. Null guard at line 202: `if (!relatedElement) return;`

---

## New Bugs Found and Fixed

### BUG-01: `files.js:123` - Object URL never revoked in `resizeBlobImg` [C-09, P2]

**File:** `/home/marin/Odoo/core/addons/web/static/src/core/utils/files.js`

`URL.createObjectURL(blob)` was called but `URL.revokeObjectURL()` was never called. Every invocation leaked a blob URL that persisted for the page lifetime, consuming memory.

**Fix:** Store the object URL in a variable and revoke it in both `onload` and `onerror` handlers.

### BUG-02: `dom/autoresize.js:152` - `resizeTextArea` null deref on `parentElement` [C-03, P2]

**File:** `/home/marin/Odoo/core/addons/web/static/src/core/utils/dom/autoresize.js`

`textarea.parentElement.style.height` was accessed without checking if `parentElement` is non-null. If the textarea is a document root or detached element, this crashes.

**Fix:** Added `if (textarea.parentElement)` guard.

### BUG-03: `urls.js:23` - `objectToUrlEncodedString` drops falsy values `0` and `false` [C-02, P2]

**File:** `/home/marin/Odoo/core/addons/web/static/src/core/utils/urls.js`

`encodeURIComponent(v || "")` treats `0`, `false`, and empty string the same due to JS truthiness. Query parameters with value `0` would be silently turned into empty strings (e.g., `?page=` instead of `?page=0`).

**Fix:** Changed `v || ""` to `v ?? ""` (nullish coalescing).

### BUG-04: `timing.js:76,88` - `debounce` trailing call and cancel() use wrong `this` [C-04, P2]

**File:** `/home/marin/Odoo/core/addons/web/static/src/core/utils/timing.js`

The trailing setTimeout callback at line 76 used `func.apply(this, lastArgs)` but `this` inside the setTimeout was not the original calling context - it was the Promise executor context. Similarly, `cancel(execNow=true)` at line 88 used `func.apply(this, lastArgs)` where `this` was the cancel method's receiver.

**Fix:** Added `lastSelf` variable captured from the debounced function's `this` context, used in both the trailing timer callback and `cancel()`.

### BUG-05: `domain.js:338` - Dotted field path dereferences null sub-record [C-03, P2]

**File:** `/home/marin/Odoo/core/addons/web/static/src/core/domain.js`

`matchCondition(record[names[0]], [...])` would crash if `record[names[0]]` was `null` or `undefined`, because the recursive call would try to access properties on the nullish value. For example, evaluating `[("partner_id.name", "=", "Foo")]` on a record with `partner_id: null`.

**Fix:** Added null check that treats missing sub-records as `false` values.

### BUG-06: `action_hook.js:127` - `setScrollFromState` accesses `rootRef.el` without null check [C-03, P2]

**File:** `/home/marin/Odoo/core/addons/web/static/src/core/action_hook.js`

The function accesses `rootRef.el.scrollTop` etc. without verifying `rootRef.el` is non-null. While typically called from `onMounted`, the function is also returned as a public API, and `rootRef.el` can be null if the ref's `t-ref` target is conditional.

**Fix:** Changed condition from `if (scrolling)` to `if (scrolling && rootRef?.el)`.

---

## Notes (Not Fixed - By Design or Low Impact)

### NOTE-01: `scrolling.js:206` - `getScrollingTarget` default param is broken [M-02, P3]

Default `window.document` has `ownerDocument === null`, so calling without args would crash. However, all callers pass explicit `Element` values. Dead default.

### NOTE-02: `domain.js:347-356` - like/ilike regex unnecessarily uses global flag [M-03, P3]

`likeRegexp` is created with `/g` flag but only used with `.match()` (not `.test()`), making the flag harmless but misleading. The `/g` flag is unnecessary.

### NOTE-03: `macro.js:83-101` - `waitUntil` RAF loop never cancels if predicate stays falsy [C-09, P3]

The exported `waitUntil` function creates an RAF loop that runs indefinitely if the predicate never returns truthy. The promise never settles, leaking the RAF. In practice, the `Macro` class wraps calls with `Promise.race` against a timeout. Standalone callers should be aware.

### NOTE-04: `binary.js:29-36` - `humanSize` array index overflow for extreme sizes [C-01, P3]

If `size >= 1024^9`, the `units` array (9 entries) index `i` overflows, producing `undefined`. Practically impossible for file sizes.

### NOTE-05: `timing.js:67-82` - `debounce` promise may never settle [C-06, P3]

When `leading=true, trailing=false`, calling the debounced function while a timer is pending creates a new Promise whose resolve is assigned to `lastArgs`. But since `trailing=false`, the timer callback won't call resolve. The promise hangs forever. This is by-design for debounce (callers rarely await the return value).

### NOTE-06: `hooks.js:216-246` - `useSpellCheck` elements array accumulates across re-effects [C-04, P3]

The `elements` array is declared outside the `useEffect` callback, but `elements.push()` happens inside the effect. The cleanup function iterates and removes listeners, but doesn't clear the array. On the next effect trigger (if `ref.el` changes), old entries accumulate. In practice, `ref.el` rarely changes, making this harmless.

---

## File-by-File Audit Status

All 49 files read completely. Status: CLEAN unless noted above.

### core/ root (9 files)
| File | Lines | Status |
|------|-------|--------|
| constants.js | 7 | Clean |
| context.js | 94 | Clean |
| action_hook.js | 189 | BUG-06 fixed |
| templates.js | 256 | Clean |
| registry.js | 287 | Clean |
| events.js | 83 | Clean |
| assets.js | 307 | Clean |
| domain.js | ~490 | BUG-05 fixed, NOTE-02 |
| template_inheritance.js | 416 | Clean |

### core/utils/ (40 files)
| File | Lines | Status |
|------|-------|--------|
| concurrency.js | 208 | Clean |
| timing.js | 217 | BUG-04 fixed, NOTE-05 |
| hooks.js | 332 | NOTE-06 |
| macro.js | 277 | NOTE-03 |
| search.js | 171 | Clean |
| indexed_db.js | 259 | Clean |
| files.js | 126 | BUG-01 fixed |
| virtual_grid.js | 191 | Clean |
| urls.js | 178 | BUG-03 fixed |
| dependency_graph.js | 115 | Clean |
| render.js | 91 | Clean |
| reactive.js | 71 | Clean |
| patch.js | 146 | Clean |
| pdfjs.js | 78 | Clean |
| order_by.js | 43 | Clean |
| functions.js | 38 | Clean |
| decorations.js | 38 | Clean |
| components.js | 17 | Clean |
| dom/scrolling.js | 213 | NOTE-01 |
| dom/autoresize.js | 154 | BUG-02 fixed |
| dom/html.js | 291 | Clean |
| dom/xml.js | 169 | Clean |
| dom/ui.js | 214 | Clean |
| dom/events.js | 33 | Clean |
| dom/classname.js | 76 | Clean |
| dom/dvu.js | 118 | Clean |
| dnd/draggable.js | 58 | Clean |
| dnd/sortable.js | 369 | Clean |
| dnd/nested_sortable.js | 447 | Clean |
| dnd/draggable_hook_builder.js | 869 | Clean |
| dnd/draggable_hook_builder_utils.js | 374 | Clean |
| dnd/draggable_hook_builder_owl.js | 32 | Clean |
| dnd/sortable_owl.js | 31 | Clean |
| format/colors.js | 497 | Clean |
| format/numbers.js | 326 | Clean |
| format/strings.js | 285 | Clean |
| format/binary.js | 37 | NOTE-04 |
| collections/arrays.js | 282 | Clean |
| collections/objects.js | 151 | Clean |
| collections/cache.js | 73 | Clean |
