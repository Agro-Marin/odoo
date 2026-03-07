# Phase 15 — views/ pivot + graph + settings + rest Audit Output

**Scope**: `static/src/views/` excluding list/, form/, kanban/, calendar/ — ~51 files, ~10,908 lines
**Status**: COMPLETE — 2 P1, 1 P2, 1 P3 fixed; 5 notes documented

---

## Fixed Findings

### `settings/settings_page.js:54` — [P1] C-02 — Destructuring from fallback `0` yields `undefined`

**Before**: `const { scrollTop } = this.scrollMap[currentTab] || 0;`
**Problem**: Destructuring `{ scrollTop }` from `0` gives `undefined`, not `0`.
**Fix**: `const { scrollTop } = this.scrollMap[currentTab] || { scrollTop: 0 };`

---

### `settings/widgets/res_config_invite_users.js:136` — [P1] C-02 — Array always truthy

**Before**: `if (emailsLeftToProcess)` — always `true` for arrays (even `[]`).
**Fix**: `if (emailsLeftToProcess.length)`

---

### `pivot/pivot_measurements.js:63` — [P2] C-02 — `instanceof Boolean` never matches primitives

**Before**: `measurement instanceof Boolean` — always `false` for primitive `true`/`false`.
**Fix**: `typeof measurement === "boolean"`

---

### `settings/settings_page.js` — [P3] M-02 — Debug placeholder `plop` renamed to `anchor`

---

## Documented (Not Fixed)

- `graph_chart_config.js`: Color scheme read at module load (stale if user switches theme)
- `graph_model.js`: `measures.slice(-1)` used as object key (works but produces `["name"]` string)
- `export_data_dialog.js`: `find` return used as boolean (works but intent unclear)
- `view_hook.js`: Unhandled async in onMounted
- `view_button_hook.js`: `Promise.reject` error re-throw pattern
