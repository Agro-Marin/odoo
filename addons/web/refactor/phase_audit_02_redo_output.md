# Phase 2 Audit (Redo) - Fresh Re-audit

**Date**: 2026-03-07
**Scope**: browser/, errors/, colors/, position/, network/ (16 files, ~3,018 lines)

---

## Summary

| Severity | New Findings | Fixed | Flagged Only |
|----------|-------------|-------|--------------|
| [P1]     | 0           | 0     | 0            |
| [P2]     | 5           | 4     | 1            |
| [P3]     | 6           | 0     | 6            |
| **Total** | **11**     | **4** | **7**        |

## Previous Findings Verification

| # | Finding | Status |
|---|---------|--------|
| 1 | `error_utils.js:196` infinite loop in annotateTraceback | **Still fixed** - both `lineIndex` and `frameIndex` advance properly (line 196-207) |
| 2 | `error_utils.js:148` error.stack null guard | **Still fixed** - `error.stack ?? ""` at line 140 |
| 3 | `colors.js:152` hexToRGBA crashes on non-matching hex | **Still fixed** - fallback to `rgba(0,0,0,${opacity})` at line 154 |
| 4 | `colors.js:66-69` violet comment numbering | **Still fixed** - numbering is sequential (#1..#4) |
| 5 | `assets.js:75` pagehide listener accumulates | **Not in scope** (assets.js is outside this audit scope) |

---

## New Findings

### FIXED

#### F-01 [P2] `browser.js:117` - `makeRAMLocalStorage().key()` ignores index parameter (C-01)

**File**: `/home/marin/Odoo/core/addons/web/static/src/core/browser/browser.js`

The `Storage.key(index)` API should return the name of the nth key, or `null` if `index >= length`. The implementation always returned `""` regardless of input.

**Before**:
```js
key() {
    return "";
}
```

**After**:
```js
key(index) {
    return Object.keys(store)[index] ?? null;
}
```

**Impact**: Any code relying on `localStorage.key(n)` in Safari Private Browsing mode would get wrong results. Low frequency but incorrect behavior.

---

#### F-02 [P2] `position/utils.js:355` - `if (maxHeight)` skips `maxHeight: 0` (C-03)

**File**: `/home/marin/Odoo/core/addons/web/static/src/core/position/utils.js`

When `shrink` is enabled and the computed available height is 0, `Math.floor(0)` produces `maxHeight: 0`. The condition `if (maxHeight)` evaluates `if (0)` as falsy, so the `maxHeight: 0px` style is never applied. The popper remains at full height instead of being collapsed.

**Before**:
```js
if (maxHeight) {
```

**After**:
```js
if (maxHeight !== undefined) {
```

**Impact**: Edge case where a popper overflows the container when shrink mode should collapse it to zero height.

---

#### F-03 [P2] `rpc_cache.js:145-152` - `checkSize()` unhandled rejection (C-07)

**File**: `/home/marin/Odoo/core/addons/web/static/src/core/network/rpc_cache.js`

`navigator.storage.estimate()` can throw in insecure contexts (HTTP, certain iframes). The fire-and-forget `this.checkSize()` in the constructor would produce an unhandled promise rejection.

**Fix**: Wrapped `navigator.storage.estimate()` in try/catch.

---

#### F-04 [P2] `rpc_cache.js:201-211` - Unhandled crypto encryption rejection (C-07)

**File**: `/home/marin/Odoo/core/addons/web/static/src/core/network/rpc_cache.js`

`this.crypto.encrypt(result).then(...)` had no `.catch()`. If `SubtleCrypto.encrypt()` fails (insecure context, invalid key), the rejection is unhandled.

**Fix**: Added `.catch()` to silently skip disk caching on encryption failure.

---

#### F-05 [P3] `download.js:257` - `options.data` crash when undefined (C-02)

**File**: `/home/marin/Odoo/core/addons/web/static/src/core/network/download.js`

`Object.entries(options.data)` throws `TypeError` if `options.data` is undefined. All current callers always pass `data`, but the API accepts arbitrary options objects.

**Fix**: `Object.entries(options.data || {})` - defensive guard.

---

### FLAGGED (not fixed)

#### F-06 [P2] `content_disposition.js:80,177-218` - Stateful regex `lastIndex` not reset on exception (C-01)

**File**: `/home/marin/Odoo/core/addons/web/static/src/core/network/content_disposition.js`

`PARAM_REGEXP` (line 80) uses the `g` flag and is module-scoped. The `parse()` function sets `PARAM_REGEXP.lastIndex` at line 177. If any `throw` at lines 182, 190, 198, or 218 fires, `lastIndex` remains dirty. The next call to `parse()` with a valid string starts matching from the wrong position, potentially producing incorrect results or false "invalid parameter format" errors.

**Not fixed**: File is explicitly marked as vendored (`/* eslint-disable */` wrapper, MIT license header from `content-disposition` npm package). Maintaining minimal diff for upgradability.

**Recommended fix**: Reset `PARAM_REGEXP.lastIndex = 0` at the start of `parse()`.

---

#### F-07 [P3] `router.js:166,169` - `splice` with potentially -1 indexOf is fragile (M-01)

**File**: `/home/marin/Odoo/core/addons/web/static/src/core/browser/router.js`

`pathKeysToOmit.splice(pathKeysToOmit.indexOf("active_id"), 1)` - if `"active_id"` were ever removed from `_hiddenKeysFromUrl`, `indexOf` returns `-1` and `splice(-1, 1)` silently removes the last element. Currently safe because `_hiddenKeysFromUrl` always contains `active_id` and `resId` (set in `startRouter`), but fragile.

---

#### F-08 [P3] `rpc_cache.js:188` - Typo `onFullfilled` should be `onFulfilled` (M-02)

**File**: `/home/marin/Odoo/core/addons/web/static/src/core/network/rpc_cache.js`

Local variable name `onFullfilled` (double-l) is a misspelling. No functional impact.

---

#### F-09 [P3] `position_hook.js:127,137` - Uses `window` directly instead of `browser` (M-01)

**File**: `/home/marin/Odoo/core/addons/web/static/src/core/position/position_hook.js`

`window.addEventListener("resize", ...)` and `window.removeEventListener("resize", ...)` bypass the `browser` facade, making the resize listener un-patchable in tests.

---

#### F-10 [P3] `colors.js:182-221` - `lightenColor`/`darkenColor` assume `#` prefix (C-02)

**File**: `/home/marin/Odoo/core/addons/web/static/src/core/colors/colors.js`

Both functions use `color.slice(1, 3)` etc., assuming the input starts with `#`. If called with a bare hex string (e.g., `"FF0000"`), they produce `NaN`-based garbage. In contrast, `hexToRGBA` handles both formats via regex. All current callers pass `#`-prefixed colors from `getColor()`.

---

#### F-11 [P3] `colors.js:121,125` - `getColor()` treats `null` paletteSizeOrName as `<= 6` (C-03)

**File**: `/home/marin/Odoo/core/addons/web/static/src/core/colors/colors.js`

`null <= 6` evaluates to `true` (null coerces to 0), so passing `null` selects "sm" palette instead of falling through to "xl" default. All current callers pass valid values.

---

## File-by-File Audit Notes

### `browser/browser.js` (122 lines)
- **F-01**: `key()` method fixed
- `innerHeight`/`innerWidth` defined both as static values (line 62-63) and as getters (line 79-86). The getters override the static values. The static assignment is dead code but harmless.
- `makeRAMLocalStorage`: `StorageEvent` dispatch on `setItem`/`removeItem` is a nice touch for cross-tab simulation.

### `browser/cookie.js` (54 lines)
- `cookie.set(key, undefined)` produces malformed cookie string `"path=/; max-age=31536000"` (sets `path` as cookie name). Dead code path - all callers pass values. Acceptable.
- `cookie.get()` splits on `"; "` (with space). If a cookie value contains "; " this would mis-parse. Standard browser behavior puts semicolon-space between cookies, so this is correct.

### `browser/feature_detection.js` (133 lines)
- Clean. All functions are simple UA/feature checks.
- `navigator.platform` is deprecated but still needed for iPad detection.

### `browser/anchor_scroll.js` (13 lines)
- Clean. Single-purpose module.

### `browser/hotkeys.js` (79 lines)
- Clean. Handles edge cases (IME, missing `ev.key`, non-Latin keyboards) correctly.
- Modifier deduplication at line 74 prevents "control+control" output.

### `browser/router.js` (435 lines)
- **F-07**: Fragile `splice(indexOf(...))` pattern
- Complex but well-structured URL state management.
- `cast()` function correctly handles edge cases (empty strings, NaN, numeric strings).
- Event listeners registered at module load (popstate, pageshow, click) - appropriate for SPA lifecycle.

### `errors/error_utils.js` (210 lines)
- Previous fixes confirmed intact (F-01, F-02 from Phase 1).
- `fullAnnotatedTraceback` re-throw mechanism is complex but correct.
- `annotateTraceback` loop termination is correct (both indices advance).

### `errors/uncaught_errors.js` (53 lines)
- Clean. Simple error class hierarchy.

### `colors/colors.js` (222 lines)
- Previous fixes confirmed intact (F-03, F-04 from Phase 1).
- **F-10, F-11**: Minor robustness issues flagged.
- `getColors` falls through to `COLORS_XL` for unknown palette names (line 112). Acceptable default.

### `position/position_hook.js` (151 lines)
- **F-09**: Direct `window` usage instead of `browser`
- `batchedUpdate` correctly prevents concurrent updates via `executingUpdate` flag.
- `useEffect` cleanup properly removes all event listeners.

### `position/utils.js` (364 lines)
- **F-02**: `maxHeight` falsy check fixed
- Complex positioning algorithm with proper overflow handling.
- `Math.floor`/`Math.ceil` rounding used consistently for sub-pixel precision.

### `network/rpc.js` (218 lines)
- `promise.abort` correctly handles XHR lifecycle (abort event fires separately from load/error).
- `rpcId++` monotonically increases - no overflow risk in practice (Number.MAX_SAFE_INTEGER ~9 quadrillion).
- `validateRPCSettings` provides clear error messages for invalid settings.

### `network/rpc_cache.js` (310 lines)
- **F-03, F-04, F-08**: Three issues found (two fixed, one flagged)
- Complex caching with RAM + encrypted IndexedDB layers.
- Promise resolution semantics are correct (multiple `resolve` calls are no-ops).
- `invalidateByModel` correctly handles both RAM and IndexedDB layers.

### `network/rpc_dedup.js` (63 lines)
- Clean. Simple and correct deduplication via Map.
- `JSON.stringify` key ordering is consistent within a single JS engine session.
- `.finally()` ensures cleanup on both success and failure.

### `network/content_disposition.js` (248 lines)
- **F-06**: Stateful regex issue flagged (not fixed, vendored)
- RFC-compliant parsing with proper quoted-string and extended value handling.
- `decodefield` correctly handles UTF-8 and ISO-8859-1 charsets.

### `network/download.js` (346 lines)
- **F-05**: Defensive guard added for `options.data`
- Vendored `_download` function has legacy code paths (MozBlob, WebKitBlob, msSaveBlob) that are dead code in modern browsers. Not modified per vendored code policy.
- `configureBlobDownloadXHR` correctly handles 200, 502, and error responses.
- Repackaging as `application/octet-stream` prevents browser PDF/office viewers from intercepting downloads.
