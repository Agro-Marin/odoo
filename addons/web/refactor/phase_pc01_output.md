# Phase PC-01 — `core/utils/` Audit Output

**Scope**: `static/src/core/utils/` — flat files + `dom/` + `dnd/` + `format/` + `collections/`
**File count**: 38
**Status**: COMPLETE — 5 bugs fixed, 3 SKIPs documented

---

## Fixed Findings

---

### `dom/scrolling.js:161` — [P1] C-05 — RTL detection always false

**Code**:
```js
const isRTL = scrollableEl.classList.contains(".o_rtl");
```

**Problem**: `classList.contains()` expects a bare class name, not a CSS selector — the leading `.` makes this always return `false`, permanently disabling RTL scrollbar compensation in every browser.

**Fix**:
```js
const isRTL = scrollableEl.classList.contains("o_rtl");
```

---

### `dom/autoresize.js:39,50` — [P1] C-09 — `removeEventListener` uses wrong function reference

**Code**:
```js
el.addEventListener("input", () => resize(true));    // line 39: anonymous arrow
// ...
el.removeEventListener("input", resize);             // line 50: different reference!
```

**Problem**: The arrow function `() => resize(true)` and `resize` are different objects. `removeEventListener` requires the exact same reference that was passed to `addEventListener`. The listener is never removed → memory leak and potential double-invocation after component teardown.

**Fix**:
```js
const inputHandler = () => resize(true);
el.addEventListener("input", inputHandler);
// ...
el.removeEventListener("input", inputHandler);
```

---

### `search.js:120` — [P1] C-05 — `fuzzyLevenshteinLookup` returns the search term instead of the matched candidate

**Code**:
```js
list.forEach((candidate) => {
    if (candidate.includes(pattern)) {
        results.push({ score: 0, elem: pattern });  // pushes the query, not the match
```

**Problem**: When a candidate substring-contains the pattern (exact match, score 0), the code pushes `elem: pattern` (the search string typed by the user) instead of `elem: candidate` (the item from the list). Callers receive their own query back as search results.

**Fix**:
```js
results.push({ score: 0, elem: candidate });
```

---

### `indexed_db.js:132,140` — [P1] C-06 — Missing `return` causes IndexedDB writes to not be awaited

**Code**:
```js
// line 130-134 — first branch: version not set
this._execute((db) => {
    if (db) {
        this._write(db, VERSION_TABLE, VERSION_KEY, version);  // not returned
    }
}).then(resolve);

// line 136-142 — second branch: version mismatch
this._deleteDatabase(() => {
    this._execute((db) => {  // not returned from deleteDatabase callback
        if (db) {
            this._write(db, VERSION_TABLE, VERSION_KEY, version);  // not returned
        }
    });
}).then(resolve);
```

**Problem**: `_execute` wraps its callback in `Promise.resolve(callback(db))`. When the callback doesn't `return` its promise, `Promise.resolve(undefined)` resolves immediately — before the IndexedDB write transaction completes. `resolve()` is then called with an open write still in flight. The version record may not be persisted before the caller proceeds to use the database.

**Fix**:
```js
this._execute((db) => {
    if (db) {
        return this._write(db, VERSION_TABLE, VERSION_KEY, version);
    }
}).then(resolve);

this._deleteDatabase(() => {
    return this._execute((db) => {
        if (db) {
            return this._write(db, VERSION_TABLE, VERSION_KEY, version);
        }
    });
}).then(resolve);
```

---

### `dnd/draggable_hook_builder.js:160` — [P1] C-04 — `preventClick` in factory scope shared across all hook instances

**Code**:
```js
export function makeDraggableHook(hookParams) {
    // ...
    const makeError = (reason) => new Error(`...`);
    let preventClick = false;   // ← factory scope: one copy for ALL components

    return {
        [hookName](params) {
            // onClick, onPointerDown, dragEnd all close over the shared variable
```

**Problem**: `makeDraggableHook` is called once at module load time (e.g. `useDraggable`, `useNestedSortable` are module-level constants). The returned hook function is then used by every component instance. They all share the single `preventClick` variable. A drag on component A that sets `preventClick = true` suppresses synthetic clicks on component B until B's next `onPointerDown` resets it.

**Fix**:
```js
export function makeDraggableHook(hookParams) {
    // ...
    const makeError = (reason) => new Error(`...`);

    return {
        [hookName](params) {
            let preventClick = false;   // ← per-instance: each component gets its own
```

---

## Skip Registry

---

### `core/utils/hooks.js` — `useSpellCheck` elements array accumulates — SKIP

The `elements` array inside `useSpellCheck` has entries pushed in `useEffect` but is never cleared. However, the cleanup function correctly removes listeners from each element. The array growing indefinitely would only matter if the same hook instance survived thousands of DOM swaps without unmounting — acceptable in practice.

---

### `dnd/sortable.js` — `delete sortableParams.setupHooks` mutates caller's object — SKIP

The `useSortable` hook deletes `setupHooks` from the `params` argument before forwarding to `nativeMakeDraggableHook`. This mutates the caller's object. Intentional: `sortable.js` is a thin adapter that strips the `setupHooks` key from the config before delegating. All callers pass a fresh object literal. Low risk in practice.

---

### `files.js` — `URL.createObjectURL` not revoked in `resizeBlobImg` — SKIP

`resizeBlobImg` creates an object URL for a canvas blob but never calls `URL.revokeObjectURL`. The blob is freed when the page navigates or the document is closed. For a resize utility called on file-upload interaction, the window lifetime is short enough that this is acceptable. Fixing it would require restructuring the return-blob async chain to track the URL handle — disproportionate complexity.

---

## Files with No Findings

`concurrency.js`, `timing.js`, `hooks.js` (skip noted), `macro.js`, `format/numbers.js`,
`format/strings.js`, `format/colors.js`, `format/binary.js`, `collections/arrays.js`,
`collections/objects.js`, `collections/cache.js`, `dom/html.js`, `dom/xml.js`, `dom/ui.js`,
`dom/events.js`, `dom/classname.js`, `dom/dvu.js`, `dnd/nested_sortable.js`,
`dnd/draggable_hook_builder_utils.js`, `dnd/sortable.js` (skip noted), `dnd/draggable.js`,
`dnd/draggable_hook_builder_owl.js`, `dnd/sortable_owl.js`, `virtual_grid.js`, `urls.js`,
`dependency_graph.js`, `render.js`, `reactive.js`, `patch.js`, `files.js` (skip noted),
`pdfjs.js`, `order_by.js`, `functions.js`, `decorations.js`
