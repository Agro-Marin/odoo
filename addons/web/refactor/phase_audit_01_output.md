# Phase 1 — core/ root + core/utils/ Audit Output

**Scope**: `static/src/core/` root (9 files) + `static/src/core/utils/` (40 files)
**File count**: 49
**Status**: COMPLETE — 2 correctness bugs fixed, 6 performance improvements, 1 SKIP

Files — `core/` root:
`domain.js`, `registry.js`, `assets.js`, `events.js`, `context.js`,
`template_inheritance.js`, `templates.js`, `action_hook.js`, `constants.js`

Files — `core/utils/`:
`concurrency.js`, `timing.js`, `hooks.js`, `macro.js`, `search.js`,
`indexed_db.js`, `files.js`, `virtual_grid.js`, `urls.js`,
`dependency_graph.js`, `render.js`, `reactive.js`, `patch.js`, `pdfjs.js`,
`order_by.js`, `functions.js`, `decorations.js`, `components.js`,
`dom/scrolling.js`, `dom/autoresize.js`, `dom/html.js`, `dom/xml.js`,
`dom/ui.js`, `dom/events.js`, `dom/classname.js`, `dom/dvu.js`,
`dnd/draggable_hook_builder.js`, `dnd/draggable_hook_builder_utils.js`,
`dnd/draggable_hook_builder_owl.js`, `dnd/draggable.js`, `dnd/sortable.js`,
`dnd/sortable_owl.js`, `dnd/nested_sortable.js`,
`format/numbers.js`, `format/strings.js`, `format/colors.js`, `format/binary.js`,
`collections/arrays.js`, `collections/objects.js`, `collections/cache.js`

---

## Fixed Correctness Findings

---

### `core/utils/dnd/sortable.js:196-204` — [P2] C-03 — `ev.relatedTarget` null dereference in `onElementComplexPointerLeave`

**Code** (before fix):
```js
const onElementComplexPointerLeave = (ev) => {
    if (ctx.haveAlreadyChanged) {
        return;
    }
    const element = /** @type {HTMLElement} */ (ev.currentTarget);
    const elementRect = element.getBoundingClientRect();
    const relatedElement = /** @type {HTMLElement} */ (ev.relatedTarget);
    const relatedElementRect = relatedElement.getBoundingClientRect(); // CRASH
```

**Problem**: `PointerEvent.relatedTarget` is `null` when the pointer exits the browser window
entirely (no element to move *to*). Calling `null.getBoundingClientRect()` throws
`TypeError: Cannot read properties of null`. This handler runs during non-clone sortable
drag operations when the user drags near the window edge — the crash interrupts the active
drag sequence, leaving the DOM in a partially modified state (placeholder not removed,
`DRAGGED_CLASS` not cleared).

**Fix**: Guard `relatedTarget` before dereferencing — return early since no sibling
comparison is possible when the pointer leaves the viewport.

---

### `core/template_inheritance.js:114` — [P3] C-05 — Stateful `/g` regex with `.test()` causes alternating debug warning misses

**Code** (before fix):
```js
const CLASS_CONTAINS_REGEX = /contains\(@class.*\)/g;
// ...
if (CLASS_CONTAINS_REGEX.test(xpath)) {  // lastIndex persists between calls
```

**Problem**: The `/g` (global) flag on a `RegExp` object makes `.test()` stateful —
after a successful match, `lastIndex` is advanced past the match position. On the next
call with a different string, the search starts from the leftover `lastIndex`, potentially
missing a valid match at an earlier position. This causes the `contains(@class...)`
deprecation warning to fire only on alternating matching XPaths (1st, 3rd, 5th...).
The `/g` flag is only needed for `.matchAll()`, `.replaceAll()`, or iterated `.exec()` —
never for standalone `.test()`.

**Fix**: Remove the `/g` flag. The regex is only used with `.test()` which needs a
single boolean result per call.

---

## Fixed Performance Findings

---

### `core/domain.js:36-54` — [P2] P-01 — `Domain.combine` was O(n²) via recursive `.slice(1)`

**Code** (before fix):
```js
static combine(domains, operator) {
    // ...
    const domain2 = Domain.combine(domains.slice(1), operator);
    // ...
    value: [...astValues1, ...astValues2],
```

**Problem**: For N domains, the recursive approach created N-1 intermediate Domain objects,
each with a `.slice(1)` array copy and `[...spread1, ...spread2]` concatenation. The total
work was O(n²) in AST nodes. `Domain.and()` / `Domain.or()` are called from search views
when combining filter domains — typically 5-10 domains per search execution, but can grow
with complex faceted search.

**Fix**: Iterative approach — single loop collects all AST values into one array, then
creates one Domain. O(n) in AST nodes.

---

### `core/domain.js:464-480` — [P2] P-05 — `matchDomain` allocated two temporary arrays per evaluation

**Code** (before fix):
```js
const reversedDomain = Array.from(domain).toReversed();
```

**Problem**: `Array.from(domain)` creates a copy, then `.toReversed()` creates another.
Two temporary arrays per `Domain.contains()` call. This is in the hot path for client-side
domain evaluation — called per-record for sample data generation, search panel filtering,
and kanban/calendar client-side filtering.

**Fix**: Iterate backwards with a `for` loop index. Zero temporary arrays.

---

### `core/domain.js:345-356` — [P3] P-05 — `matchCondition` created both case-sensitive and case-insensitive regex

**Code** (before fix):
```js
if (["like", "not like", "ilike", "not ilike"].includes(operator)) {
    likeRegexp = new RegExp(..., "g");
    ilikeRegexp = new RegExp(..., "gi");
}
```

**Problem**: Both `likeRegexp` (case-sensitive) and `ilikeRegexp` (case-insensitive) were
created for any like operator, but only one is ever used per call. For non-like operators
(the common `=`, `!=`, `in`, `not in`), no regex is created, so the hot path was already
fast — but the like path allocated an unnecessary RegExp object.

**Fix**: Two separate `if` branches — only create the needed regex.

---

### `core/utils/dom/scrolling.js:88-91` — [P2] P-02 — `scrollTo` called `getBoundingClientRect()` 5 times on 2 elements

**Code** (before fix):
```js
const scrollBottom = scrollable.getBoundingClientRect().bottom;
const scrollTop = scrollable.getBoundingClientRect().top;
const elementBottom = element.getBoundingClientRect().bottom;
const elementTop = element.getBoundingClientRect().top;
// ...later...
Math.ceil(element.getBoundingClientRect().height)
```

**Problem**: `getBoundingClientRect()` forces layout reflow. Called 3 times on `scrollable`
and 3 times on `element` (including the `.height` read in the scroll-down branch), when
2 calls total (one per element) would suffice. Layout thrashing is especially costly
during scroll-into-view operations which may chain multiple scrolls.

**Fix**: Store both rects in variables, read all needed properties from the cached rects.

---

### `core/utils/timing.js:132-173` — [P2] P-05 — `throttleForAnimation` used `Set` + spread where a single variable suffices

**Code** (before fix):
```js
const calls = new Set();
// ...in pending():
const { args, resolve } = [...calls].pop();
calls.clear();
```

**Problem**: Only the last pending call matters (all earlier calls are discarded). Using a
`Set` and then `[...calls].pop()` allocated a temporary array on every animation frame tick
during drag operations. The Set itself also has higher per-operation overhead than a plain
variable assignment.

**Fix**: Replace `calls` Set with a single `lastCall` variable. Assignment and nulling
instead of Set operations and array spread.

---

### `core/utils/search.js:139-170` — [P3] P-05 — Levenshtein allocated full (n+1)×(m+1) matrix

**Code** (before fix):
```js
const distanceMatrix = [];
for (let i = 0; i <= aLength; i++) {
    distanceMatrix[i] = [];
    for (let j = 0; j <= bLength; j++) {
        distanceMatrix[i][j] = 0;
    }
}
```

**Problem**: The classic Levenshtein algorithm only needs the previous row and the current
row — `distanceMatrix[i-1][j]`, `distanceMatrix[i][j-1]`, `distanceMatrix[i-1][j-1]`.
Allocating the full (n+1)×(m+1) matrix wastes O(n×m) memory. For `fuzzyLevenshteinLookup`
iterating over many candidates (e.g., command palette), this adds up.

**Fix**: Two-row approach with swap. O(min(n,m)) memory. Also added early returns for
empty strings and ensures the shorter string is used for the row arrays.

---

## Skip Registry

---

### `core/template_inheritance.js:14-20` — SKIP — `getTranslationContext` infinite recursion if no ancestor has `TCTX`

```js
function getTranslationContext(node) {
    const el = /** @type {Element} */ (node);
    if (el.hasAttribute(TCTX)) {
        return el.getAttribute(TCTX);
    }
    return getTranslationContext(el.parentElement); // null if root reached
}
```

**Why it looks wrong**: `el.parentElement` is `null` at the document root, causing
`null.hasAttribute()` → TypeError on the next recursive call.

**Why it's safe**: All callers (`getNodes` → line 212, `replace` → line 309) operate
on nodes inside template trees that have already been processed by `applyInheritance`,
which sets `translationContext` on the root element via `setTranslationContext`. The
attribute is always present on at least the root ancestor. Confirmed in PC-02 as a SKIP
with the same reasoning.

---

## Delta vs PC-01 / PC-02

### PC-01 Findings (5 bugs in core/utils/)
All 5 PC-01 fixes confirmed still present and correct:
1. `dom/scrolling.js` RTL classList — CONFIRMED (fix at `.toggle("o-scrollable-rtl", ...)`)
2. `dom/autoresize.js` removeEventListener wrong ref — CONFIRMED (fix: same function ref)
3. `search.js` fuzzyLevenshtein returning query — CONFIRMED (fix: returns candidate)
4. `indexed_db.js` missing returns — CONFIRMED (fix: return promises)
5. `dnd/draggable_hook_builder.js` preventClick shared scope — CONFIRMED (moved to per-instance)

### PC-02 Findings (3 bugs in core/browser/ + core/errors/ + core/colors/ + core/position/)
PC-02 scope overlaps Phase 2 (not Phase 1). Not re-audited here.

### New Findings Not in PC-01
1. `sortable.js:203` — NEW [P2] C-03 — relatedTarget null dereference (missed by PC-01)
2. `template_inheritance.js:114` — NEW [P3] C-05 — stateful /g regex (missed by PC-01)
3. `domain.js:36` — NEW [P2] P-01 — Domain.combine O(n²) (missed by PC-01)
4. `domain.js:464` — NEW [P2] P-05 — matchDomain unnecessary array copies (missed by PC-01)
5. `domain.js:345` — NEW [P3] P-05 — matchCondition dual regex creation (missed by PC-01)
6. `dom/scrolling.js:88` — NEW [P2] P-02 — scrollTo layout thrashing (missed by PC-01)
7. `timing.js:132` — NEW [P2] P-05 — throttleForAnimation Set overhead (missed by PC-01)
8. `search.js:139` — NEW [P3] P-05 — Levenshtein full matrix allocation (missed by PC-01)

---

## Files with No Findings

`core/`: `registry.js`, `assets.js`, `events.js`, `context.js`,
`templates.js`, `action_hook.js`, `constants.js`

`core/utils/`: `concurrency.js`, `hooks.js`, `macro.js`,
`indexed_db.js`, `files.js`, `virtual_grid.js`, `urls.js`, `dependency_graph.js`,
`render.js`, `reactive.js`, `patch.js`, `pdfjs.js`, `order_by.js`, `functions.js`,
`decorations.js`, `components.js`

`core/utils/dom/`: `autoresize.js`, `html.js`, `xml.js`, `ui.js`,
`events.js`, `classname.js`, `dvu.js`

`core/utils/dnd/`: `draggable_hook_builder.js`, `draggable_hook_builder_utils.js`,
`draggable_hook_builder_owl.js`, `draggable.js`, `sortable_owl.js`, `nested_sortable.js`

`core/utils/format/`: `numbers.js`, `strings.js`, `colors.js`, `binary.js`

`core/utils/collections/`: `arrays.js`, `objects.js`, `cache.js`
