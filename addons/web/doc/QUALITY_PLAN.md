# Web Module — Quality Improvement Plan

> **Context**: Phases 1–9 of the FSD refactor (see `refactor/REFACTOR_STATE.md`) addressed
> architecture: boundary violations resolved, god objects decomposed (−1,587 lines across
> SearchModel/RelationalRecord/StaticList/GraphRenderer), error hierarchy established,
> 14 dead shims removed. JSDoc at 81% (494/612 files).
>
> This plan targets the remaining orthogonal dimension: **testability, correctness, and
> performance**. It does not revisit structural concerns already resolved.

---

## Audit Findings

### Finding 1 — Untested Pure Relational Model Modules (Testability — Critical)

Phase 6b/6d decomposed `record.js` and `static_list.js` into smaller modules but added no
unit tests for the extracted code. The relational_model directory now has 29 JS files; only
5 have dedicated test files. 18 of the 21 pure modules (no OWL imports) are completely
untested:

| File | Lines | Has test |
|------|-------|----------|
| `dynamic_list.js` | 585 | — |
| `field_metadata.js` | 317 | — |
| `static_list_command_engine.js` | 275 | — |
| `dynamic_group_list.js` | 428 | — |
| `dynamic_record_list.js` | 202 | — |
| `record_value_transforms.js` | 181 | — |
| `record_validator.js` | 98 | — |
| `record_preprocessors.js`* | 231 | — |
| `record_save.js`* | 192 | — |
| `static_list_sort.js` | 136 | — |
| `static_list_utils.js` | 149 | — |
| `field_spec.js` | 119 | — |
| `group.js` | 151 | — |
| `field_context.js` | 87 | — |
| `resequence.js` | 104 | — |
| `commands.js` | 55 | — |
| `operation.js` | 33 | — |
| `errors.js` | 37 | — |

*`record_preprocessors.js` and `record_save.js` import OWL but only for `markup()` / `reactive()` —
their core logic is structurally pure and fully testable with Hoot mocks.

**Already tested**: `command_builder.js`, `onchange_coalescer.js`, `record_utils.js`.

**Risk**: `static_list_command_engine.js` (x2many CREATE/UPDATE/DELETE command generation) and
`record_preprocessors.js` (many2one/reference/x2many/properties normalization) are the most
business-critical. Bugs here silently corrupt record saves.

---

### Finding 2 — No Test Runner Method for model/ Tests (Testability — Infrastructure)

`tests/model/*.test.js` (5 files, 2079 lines) runs inside the full 1–2h JS suite but has no
targeted `test_model` runner method in `WebSuite` / `MobileWebSuite`. This means:

- Model tests cannot be run in isolation during development (`~30s` would be achievable)
- New model unit tests from Finding 1 will be equally buried unless a method is added

`machine_doc_v1/TEST_TAGS.md` already defines the pattern: `test_core` → `@web/core`,
`test_search` → `@web/search`, etc. The model layer is the only subsystem without one.

---

### Finding 3 — Phase 6a Extracted Modules Untested (Testability — Critical)

Phase 6a created `search_query_mutations.js` (375 lines, 14 exported functions) and
`search_panel_state.js` (295 lines, 12 exported functions) by extracting pure state
mutation logic from SearchModel. Neither file has a unit test.

All 14 mutation functions (`addAutoCompletionValues`, `toggleSearchItem`, `toggleDateFilter`,
`createNewFavorite`, `clearFilters`, etc.) are pure in the sense that they take a SearchModel
instance and return a new state — they can be exercised against a minimal mock SearchModel
without mounting any component.

Existing search tests (`search_bar.test.js`, `control_panel.test.js`) test the mutations
only incidentally via UI interactions — 372 `mountView`/`click`/`contains` calls for pivot
alone gives the scale of what "incidentally" means.

---

### Finding 4 — Pure View Models Tested Only via Integration (Testability + Performance)

`pivot_model.js` (1037 lines) and `calendar_model.js` (1020 lines) are both pure (no OWL
imports). Their logic — grouping, aggregation, date range expansion, event overlap computation
— is fully exercisable as unit tests. Current state:

- `pivot_model.js`: 372 `mountView`/`click`/`contains` calls in `pivot_view.test.js` — all
  integration. No `pivot_model.test.js`.
- `calendar_model.js`: no unit test file whatsoever.

Every change to pivot aggregation or calendar date logic requires a full browser render cycle
to detect. Pure unit tests for these models would cut feedback time from ~2min to <1s.

---

### Finding 5 — view_compiler Cache Coherence Bug (Correctness + Performance)

`view_compiler.js:473`:

```js
// FIXME: that function only purges the compiler's cache and NOT the cache in owl's app.
// the owl.xml function creates an internal template each time, so the cache is here to prevent
// creating new owl templates every time. If we clear the cache, new templates WILL be created,
```

The comment is cut off but the problem is clear: `CLEAR-CACHES` events call the compiler's
cache purge function, which removes compiled templates from the local `Map`. But OWL's `App`
object holds its own internal template registry. When the local cache is cleared, the
compiler recreates templates (expensive), but they accumulate in OWL's registry —
old templates are never freed. The effect is:

- On registry updates (module installs, upgrades): compiled view templates leak into OWL's
  registry indefinitely — a memory leak proportional to the number of views loaded per session.
- After a cache clear, the view re-renders from freshly compiled templates but OWL may reuse
  stale compiled versions from its own registry (depending on template name collision), meaning
  the clear is not effective.

This bug was introduced with the view caching system and survives because it only manifests
across multiple `CLEAR-CACHES` events in a long-running session.

---

### Finding 6 — Critical Field Widgets Untested (Testability — High)

42 field widget JS files have no test file. The highest-risk gaps by line count and user
impact:

| File | Lines | Impact |
|------|-------|--------|
| `many2x_autocomplete.js` | 630 | Search/create UX for all Many2one + Many2many |
| `property_definition.js` | 499 | Properties system definition editor |
| `property_value.js` | 422 | Properties value display/edit |
| `x2many_field.js` | 401 | All inline one2many/many2many lists |
| `x2many_dialog.js` | 386 | Dialog editing for x2many records |
| `input_field_hook.js` | 201 | Shared hook for all text input fields |
| `field_widths.js` | 124 | Column width computation for list view |
| `dynamic_placeholder_popover.js` | 121 | Char/text field dynamic placeholders |
| `translation_dialog.js` | 119 | Translatable field dialogs |

`many2x_autocomplete.js` is the highest priority: it drives the search, quick-create, and
create-and-edit flow for every relational field in every form view. Its 630 lines have never
been tested in isolation.

`x2many_field.js` (401 lines) and `x2many_dialog.js` (386 lines) together cover the full
inline editing lifecycle for one2many/many2many — the most complex field interaction path.

---

## Success Criteria

| Criterion | Current | Target |
|-----------|---------|--------|
| Pure `relational_model/` modules with tests | **21 / 21** | **21 / 21** ✓ |
| Targeted `test_model` runner method | present | **present** ✓ |
| Phase 6a extracted modules with unit tests | 2 / 2 | **2 / 2** ✓ |
| Pure view models with unit tests | 2 / 2 | **2 / 2** ✓ |
| `view_compiler.js` FIXME resolved | closed | **closed** ✓ |
| Critical field widgets with tests (top 6) | **6 / 6** | **6 / 6** ✓ |

---

## Phased Plan

### Phase A — Test Runner Infrastructure (prerequisite)

**Goal**: Add `test_model` method to `WebSuite` and `MobileWebSuite` so the model layer has
a fast, targeted runner like every other subsystem.

**File**: `tests/test_web.py` — add `test_model` method alongside existing `test_core`,
`test_search`, etc., pointing to `@web/model` Hoot suite group.

**Scope**: 1 file, ~10 lines. No JS changes.

**Run command after**:
```bash
> ./odoo.log && ./core/odoo-bin -c ./conf/odoo.conf -d test_db \
    --test-tags '/web:WebSuite.test_model' -u web --stop-after-init --workers=0
```

**Acceptance**: The 5 existing model test files (2079 lines) run and pass in <30s.

---

### Phase B — Relational Model Unit Tests

**Goal**: Cover the 18 untested pure modules. Implement as pure Hoot `test()` calls —
no `mountView`, no mock server, no DOM.

**New test files** (create in `static/tests/model/relational_model/`):

| Test file | Covers | Priority |
|-----------|--------|----------|
| `static_list_command_engine.test.js` | applyCommands (CREATE/UPDATE/DELETE/LINK/UNLINK) | P0 |
| `record_value_transforms.test.js` | all transform functions | P0 |
| `record_validator.test.js` | required/constraint validation logic | P0 |
| `dynamic_list.test.js` | pagination, sort, filter | P1 |
| `static_list_sort.test.js` | sort, resequence, sortBy | P1 |
| `field_metadata.test.js` | field descriptor resolution | P1 |
| `group.test.js` | group data access, counting | P1 |
| `dynamic_group_list.test.js` | grouped list operations | P1 |
| `dynamic_record_list.test.js` | flat filtered list | P2 |
| `field_spec.test.js` | spec tree construction | P2 |
| `field_context.test.js` | per-field context computation | P2 |
| `static_list_utils.test.js` | shared helpers | P2 |
| `resequence.test.js` | resequence logic | P2 |

For `record_preprocessors.js` and `record_save.js` (OWL-importing): use Hoot's `mockService`
and a minimal stub record object — test the logic paths without a real OWL environment.

**Run command**:
```bash
> ./odoo.log && ./core/odoo-bin -c ./conf/odoo.conf -d test_db \
    --test-tags '/web:WebSuite.test_model' -u web --stop-after-init --workers=0
```

**Acceptance**: All 18 modules have test files; each test file covers the module's exported
functions with at least one happy-path and one edge-case test per exported function.

---

### Phase C — Phase 6a Extracted Module Unit Tests

**Goal**: Unit tests for `search_query_mutations.js` (14 functions) and
`search_panel_state.js` (12 functions). These were the biggest Phase 6 extractions and
the most likely to regress silently.

**New test files** (create in `static/tests/search/`):

- `search_query_mutations.test.js` — test each of the 14 mutation functions against a minimal
  SearchModel stub. Key cases: `toggleDateFilter` date range boundaries, `createNewFavorite`
  payload construction, `clearFilters` scope, `deactivateGroup` cascade.
- `search_panel_state.test.js` — test the 12 panel state functions. Key cases:
  `toggleCategoryValue` exclusivity, `toggleFilterValues` multi-select, `createCategoryTree`
  and `createFilterTree` structure, `shouldWaitForData` conditions.

Both files operate on plain objects — no mountView needed. Use Hoot `expect().toEqual()` for
state assertions.

**Run command**:
```bash
> ./odoo.log && ./core/odoo-bin -c ./conf/odoo.conf -d test_db \
    --test-tags '/web:WebSuite.test_search' -u web --stop-after-init --workers=0
```

**Acceptance**: All 26 exported functions covered; `search_model.test.js` can test integration
behavior while the new files own pure-logic regression.

---

### Phase D — Pure View Model Unit Tests

**Goal**: Unit tests for `pivot_model.js` and `calendar_model.js` that exercise the models'
computation logic without mounting a full view.

**New test files**:

- `static/tests/views/pivot/pivot_model.test.js` — use the model API directly against
  mock data. Key: aggregation correctness for sum/count/avg, group expansion, comparison
  period computation, `getCell()` correctness for sparse group intersections.
- `static/tests/views/calendar/calendar_model.test.js` — key: date range filtering,
  event overlap detection, `dateToServer` / `serverToDate` round-trips, all-day vs timed
  event handling.

Both models are pure classes (no OWL). Instantiate directly:
```js
const model = new PivotModel(definition, { orm });
await model.load(searchParams);
```
with a mock ORM that returns pre-canned data.

**Run command**:
```bash
> ./odoo.log && ./core/odoo-bin -c ./conf/odoo.conf -d test_db \
    --test-tags '/web:WebSuite.test_graph_pivot,/web:WebSuite.test_calendar' \
    -u web --stop-after-init --workers=0
```

**Acceptance**: Core model logic is exercisable without `mountView`; test files run in <10s.
Existing integration tests in `pivot_view.test.js` and `calendar_view.test.js` continue to
pass and cover UI concerns.

---

### Phase E — view_compiler Cache Coherence Fix

**Goal**: Resolve `view_compiler.js:473` — the compiler's cache clear must be coherent with
OWL's internal template registry to prevent memory leaks and potential stale-template bugs.

**Investigation steps**:

1. Read `view_compiler.js` in full to understand the local `Map`-based cache structure and
   where `owl.xml` / `app.rawTemplates` is called.
2. Determine whether OWL's `App` exposes a way to unregister templates (check `@odoo/owl`
   source under `core/addons/web/static/lib/owl/`).
3. If OWL exposes `app.templates.delete(name)` or equivalent: hook the compiler's cache
   invalidation to also remove the corresponding OWL entry.
4. If OWL does not expose deletion: coordinate with the view loading cache at the
   `view_service.js` level — invalidate at source (prevent re-compilation of the same arch)
   rather than at the compiler level.

**Files in scope**: `views/view_compiler.js`, `views/view.js`, `views/view_service.js`
(and potentially `env.js` for the `CLEAR-CACHES` subscriber).

**Acceptance**: The FIXME comment is removed; a test in `view_compiler.test.js`
(`static/tests/views/`) demonstrates that after `CLEAR-CACHES`, reloading a view does not
accumulate duplicate entries in OWL's template registry.

---

### Phase F — Critical Field Widget Tests

**Goal**: Cover the 6 highest-risk untested field widgets with integration tests consistent
with the existing `static/tests/views/fields/` suite.

**Priority order**:

1. `many2x_autocomplete.test.js` — covers: dropdown open/close, search RPC calls,
   quick-create flow, `create_and_edit` dialog, `no_create`/`no_quick_create` restrictions,
   keyboard navigation (arrow keys, Enter, Escape), NewId record handling.

2. `x2many_field.test.js` + `x2many_dialog.test.js` — covers: add/remove/edit in inline
   list mode, dialog mode, x2many ORM command generation (CREATE/UPDATE/DELETE), discard,
   nested x2many.

3. `input_field_hook.test.js` — covers: debounce behavior, focus/blur lifecycle, the
   shared commitChanges path used by all text inputs.

4. `translation_dialog.test.js` — covers: loading translations, saving per-lang overrides,
   field not-translatable guard.

**Run command**:
```bash
> ./odoo.log && ./core/odoo-bin -c ./conf/odoo.conf -d test_db \
    --test-tags '/web:WebSuite.test_fields' -u web --stop-after-init --workers=0
```

**Acceptance**: Each new test file has ≥5 test cases; `test_fields` suite passes in full.

---

## Execution Order

```
Phase A  (infrastructure, ~1 day)
    └─▶ Phase B  (model unit tests, ~4 days)  — depends on Phase A runner
    └─▶ Phase C  (search unit tests, ~2 days) — independent, parallel with B
    └─▶ Phase D  (view model unit tests, ~2 days) — independent, parallel with B/C
Phase E  (view_compiler fix, ~2 days) — independent, no prerequisites
Phase F  (field widget tests, ~5 days) — independent, no prerequisites
```

Phases B, C, D can be parallelized once Phase A is done.
Phase E and F can start immediately alongside Phase A.

---

## Key File Locations

| Phase | New files | Existing files modified |
|-------|-----------|------------------------|
| A | — | `tests/test_web.py` |
| B | `static/tests/model/relational_model/*.test.js` (×13) | — |
| C | `static/tests/search/search_query_mutations.test.js`, `search_panel_state.test.js` | — |
| D | `static/tests/views/pivot/pivot_model.test.js`, `static/tests/views/calendar/calendar_model.test.js` | — |
| E | `static/tests/views/view_compiler.test.js` (new cache test) | `views/view_compiler.js`, possibly `views/view.js` / `views/view_service.js` |
| F | `static/tests/views/fields/many2x_autocomplete.test.js`, `x2many_field.test.js`, `x2many_dialog.test.js`, `input_field_hook.test.js`, `translation_dialog.test.js` | — |
