# Phase 2 — core/browser/ + core/errors/ + core/colors/ + core/position/ + core/network/ Audit Output

**Scope**: `static/src/core/browser/` (6 files) + `core/errors/` (2 files) + `core/colors/` (1 file) + `core/position/` (2 files) + `core/network/` (5 files)
**File count**: 16
**Status**: COMPLETE — 2 bugs fixed, 1 performance improvement, 0 SKIPs

Files — `core/browser/`:
`browser.js`, `cookie.js`, `feature_detection.js`, `anchor_scroll.js`, `hotkeys.js`, `router.js`

Files — `core/errors/`:
`error_utils.js`, `uncaught_errors.js`

Files — `core/colors/`:
`colors.js`

Files — `core/position/`:
`position_hook.js`, `utils.js`

Files — `core/network/`:
`rpc.js`, `rpc_cache.js`, `rpc_dedup.js`, `content_disposition.js` (vendored), `download.js` (partial vendored)

---

## Fixed Findings

---

### `core/errors/error_utils.js:196` — [P2] C-07 — Infinite loop in `annotateTraceback` when traceback has fewer location lines than frames

**Code** (before fix):
```js
while (frameIndex < frames.length) {
    const line = lines[lineIndex];
    if (!/:\d+:\d+\)?$/.test(line)) {
        lineIndex++;
        continue;
    }
    // ...annotate line...
    lineIndex++;
    frameIndex++;
}
```

**Problem**: When `lineIndex` exceeds `lines.length`, `lines[lineIndex]` is `undefined`.
`RegExp.prototype.test(undefined)` coerces the argument to the string `"undefined"`, which
never matches the `:\d+:\d+` pattern. Since `frameIndex` only advances when a line matches,
the loop never terminates. This triggers when StackTrace.js returns more frames than the
traceback has location-bearing lines — possible with modified stacks (line 177 rewrites
Firefox stacks), errors with synthetic/empty stacks, or library-internal stack munging.

The infinite loop freezes the browser tab. Because `annotateTraceback` is called from the
uncaught error handler, the user sees a frozen page instead of an error dialog.

**Fix**: Add `lineIndex < lines.length` to the while condition:
```js
while (frameIndex < frames.length && lineIndex < lines.length) {
```

---

### `core/colors/colors.js:66-69` — [P3] M-02 — Violet comment numbering copy-paste error

**Code** (before fix):
```js
"#A76DBC", // Violet #1
"#7F4295", // Violet #1   ← should be #2
"#6D2387", // Violet #1   ← should be #3
"#4F1565", // Violet #1   ← should be #4
```

**Problem**: All four Violet entries in `COLORS_XL` are labeled `#1` instead of `#1`–`#4`.
Copy-paste oversight from array authoring. Misleading for anyone extending the palette.

**Fix**: Numbered sequentially `#1` through `#4`.

---

## Fixed Performance Findings

---

### `core/utils/collections/objects.js:44-46` — [P2] P-05 — `deepCopy` used JSON round-trip instead of `structuredClone`

**Code** (before fix):
```js
export function deepCopy(object) {
    return object && JSON.parse(JSON.stringify(object));
}
```

**Problem**: `JSON.parse(JSON.stringify(x))` is the slowest deep-copy method available in
modern browsers — 2-10x slower than `structuredClone()` depending on object shape and engine.
This is in the hot path: `rpc_cache.js` calls `deepCopy()` on every cache hit (3 call sites),
and 14 total call sites exist across 8 files. The JSON approach also silently drops `Date`,
`Set`, `Map`, `undefined` values, and `NaN` — producing incorrect copies for non-JSON types.

`structuredClone()` is a native C++ implementation (available in all browsers since 2022 and
Node.js 17+) that handles all structured-cloneable types correctly and avoids the
serialization/deserialization overhead of the JSON round-trip.

**Fix**: Replace with `structuredClone(object)`. Updated JSDoc to remove the outdated
"relies on JSON" caveat. Updated tests in `objects.test.js` to verify that `Date`, `Set`,
and `Map` are now correctly preserved (previously the tests asserted they were stripped).

**Callers verified** (14 across 8 files): all pass plain objects, arrays, or primitives —
no non-cloneable types (DOM nodes, functions, Symbols) in any call site.

---

## Delta vs PC-02

### PC-02 Findings (3 bugs)
1. `error_utils.js` — error.stack null guard → CONFIRMED (fix at line 140: `?? ""`)
2. `colors/colors.js` hexToRGBA null match → CONFIRMED (fix at line 152-154: early return)
3. `assets.js` pagehide listener leak → Not in Phase 2 scope (Phase 1 — confirmed there)

### New Findings Not in PC-02
1. `error_utils.js:196` — NEW [P2] C-07 — infinite loop (missed by PC-02)
2. `colors.js:66-69` — NEW [P3] M-02 — comment numbering (missed by PC-02)
3. `objects.js:44` — NEW [P2] P-05 — deepCopy JSON round-trip → structuredClone (missed by PC-02)

---

## Files with No Findings

`core/browser/`: `browser.js`, `cookie.js`, `feature_detection.js`, `anchor_scroll.js`,
`hotkeys.js`, `router.js`

`core/errors/`: `uncaught_errors.js`

`core/position/`: `position_hook.js`, `utils.js`

`core/network/`: `rpc.js`, `rpc_cache.js`, `rpc_dedup.js`,
`content_disposition.js` (vendored, `eslint-disable`), `download.js` (partial vendored)
