# Phase 7 — search/ Audit Output

**Scope**: `static/src/search/` — 31 files, ~7,353 lines
**Status**: COMPLETE — 3 P1 bugs fixed, 2 P2 bugs fixed, 2 P3 documented

---

## Fixed Correctness Findings

---

### `search_panel/search_panel.js:284` — [P1] C-05 — `Object.keys()` on a Map returns `[]`

**Code** (before fix):
```js
filterValues = Object.keys(groups)
    .map((groupId) => nameOfCheckedValues(groups[groupId].values))
    .flat();
```

**Problem**: `groups` is a `Map` (constructed in `search_panel_fetch.js:73`). `Object.keys()` on a
Map always returns `[]` because Map entries are not own enumerable string-keyed properties.
Grouped search panel filters **never show checked values** in the control panel summary banner.

**Fix**: Replace with `[...groups.values()].map((group) => nameOfCheckedValues(group.values)).flat()`.

---

### `control_panel/control_panel.js:729-739` — [P1] C-01 — Falsy-zero bug in sort comparator

**Code** (before fix):
```js
const indexA = order.indexOf(a.id);
if (!indexA) {       // !0 is true (first element treated as missing)
    return -1;       // !(-1) is false (missing items fall through)
}
```

**Problem**: `!indexA` is `true` when `indexA === 0` (first element in order — treated as "not found")
and `false` when `indexA === -1` (actually not found — falls through to arithmetic).
Items NOT in the `order` array get `indexOf = -1` (truthy), fall through to `return indexA - indexB`,
producing negative values that sort missing items before ordered items. Embedded action tab
reordering is broken when some actions are not in the saved order array.

**Fix**: Use explicit `-1` checks: `if (indexA === -1) return 1; if (indexB === -1) return -1;`

---

### `control_panel/control_panel.js:314` — [P1] C-05 — `target.scrollingElementHeight` is not a DOM property

**Code** (before fix):
```js
if (this.scrollingElementHeight !== target.scrollingElementHeight) {
    this.oldScrollTop += target.scrollingElementHeight - this.scrollingElementHeight;
    this.scrollingElementHeight = target.scrollingElementHeight;
}
```

**Problem**: `target` is a DOM element from `ResizeObserver`. DOM elements have `scrollHeight`,
not `scrollingElementHeight`. `target.scrollingElementHeight` is always `undefined`.
On first resize event after setup (where `this.scrollingElementHeight` was set to a real number),
the condition is `number !== undefined` → true, and the arithmetic `undefined - number` → `NaN`,
permanently corrupting `this.oldScrollTop`. Mobile sticky scroll behavior breaks after any
resize event (keyboard open, orientation change).

**Fix**: Replace `target.scrollingElementHeight` with `target.scrollHeight` (3 occurrences).

---

### `utils/dates.js:330` — [P2] C-03 — `.find()` result used without null guard

**Code** (before fix):
```js
const option = periodOptions.find((option) => option.id === optionId);
const granularity = option.granularity;  // crashes if option is undefined
```

**Problem**: If `optionId` doesn't match any period option (e.g., restored favorite with stale
option IDs), `option` is `undefined` and accessing `.granularity` throws TypeError.

**Fix**: Add `if (!option) continue;` guard.

---

### `search_query_mutations.js:302-305` — [P2] C-03 — `.find()` destructured without null guard

**Code** (before fix):
```js
const { defaultYearId } = getPeriodOptions(...).find((o) => o.id === generatorId);
```

**Problem**: Same pattern — `.find()` can return `undefined`, and destructuring `undefined` throws.

**Fix**: Assign to variable first, guard with `if (!periodOption) break;`.

---

## Documented Issues (Not Fixed)

---

### `search_panel/search_panel.js:416` — [P2] C-05 — Global `document.querySelectorAll`

`document.querySelectorAll(".o_search_panel_filter_group")` should be scoped to the component's
DOM subtree. If multiple SearchPanel instances exist (dialog over list view), checkbox states
could bleed across panels. In practice, Odoo renders one SearchPanel per view, limiting exposure.
Deferred: requires OWL component root element access pattern.

---

### `search_bar_menu/search_bar_menu.js:151-162` — [P3] C-04 — One-way latch in getter

The `sharedFavorites` getter mutates `this.state.sharedFavoritesExpanded = true` when
`sharedFavorites.length <= 4`. Once set, the flag never resets. Cosmetic: favorites section
stays expanded even after user collapses it, if count was ever ≤4.

---

### `search_domain.js:87-88` — [P3] M-03 — Inconsistent return types from `computeGroupDomain()`

Returns `[]` for many2one, `{}` for many2many, `undefined` for other types. Backend handles
all cases, but the inconsistency makes the API contract unclear.

---

## Files with No Findings

search_state.js, search_bar.js, search_bar_menu.js (aside from P3), facets.js,
with_search.js, comparison_menu.js, favorite_menu.js, group_by_menu.js, filter_menu.js,
search_panel_fetch.js, search_panel_state.js, and remaining files.
