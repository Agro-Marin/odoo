# Refactoring State — Last Updated: 2026-03-05 (Phase 11 AP-09 fix)

## Current Phase: 11 — Post-Phase-10 Cleanup (COMPLETE)
## Next Action: None — all identified violations resolved or accepted

## Completed
- [x] Phase 1: Analysis & Plan (2026-03-05)
  - Output: phase1_analysis.md
  - Key decisions:
    - FSD layer assignment confirmed (shared→entities→features→pages)
    - 10 files marked SPLIT, 28 files KEEP TOGETHER
    - 9 boundary violations identified, resolution plan for each
    - 3 abstractions APPROVED (record observer move, x2ManyCommands move, tree logic extraction)
    - 3 abstractions DEFERRED (state machine, typed events, error hierarchy)
    - 1 abstraction REJECTED (plugin system — registry IS the plugin system)
    - Test architecture: mirror structure kept, tag taxonomy defined
    - Anti-patterns catalog: 11 patterns identified
- [x] Phase 2: Constants & Types (2026-03-05)
  - Created: model/relational_model/commands.js (canonical x2ManyCommands location)
  - Re-export shim: services/orm_service.js (zero consumers — all updated to canonical path)
  - Updated 8 web imports: 6 model/ files (relative ./commands), 2 fields/ files (absolute path)
  - Updated 10 core addon imports + 8 enterprise imports → canonical @web/model/relational_model/commands
  - Boundary violation #1 resolved: model/ no longer imports from services/ for x2ManyCommands
  - Plan deviation: parsers.js did NOT import x2ManyCommands (plan was incorrect); actual fields/ files were x2many_field.js and res_user_group_ids_field.js
- [x] Phase 3: Decouple Model Layer (2026-03-05)
  - field_context.js: replaced `user.activeCompany?.id` with `allowed_company_ids?.[0]` (data already on config)
  - sample_server.js: removed `import { ORM }`, receive real ORM instance via param, clone with `Object.create(orm)`
  - model.js: removed `import { user }`, pass `orm` instead of `user` to `buildSampleORM()`
  - Result: `grep "from.*@web/services" model/` returns **0 results** — target achieved
  - Plan deviation: plan said "10 files changed" — actual: 3 files changed. The plan overestimated because:
    - `user` injection via constructor (threading through RelationalModel) was unnecessary — `current_company_id` was derivable from existing `config.context.allowed_company_ids`
    - `user` param to `buildSampleORM` was dead code (ORM constructor ignored it) — replaced with ORM instance injection
- [x] Phase 4: Decouple Fields from Model (2026-03-05)
  - Created: fields/hooks/record_observer.js (canonical useRecordObserver location)
  - Re-export shim: model/relational_model/record_hooks.js (zero consumers — all updated to canonical path; shim deleted Phase 11)
  - Updated 9 web imports: 8 fields/ files + 1 views/kanban_record.js → new path
  - Updated 12 core addon imports + 11 enterprise imports + 1 addons_custom import → canonical @web/fields/hooks/record_observer
  - DomainSelectorDialog: removed import from search_model.js, injected via with_search.js services
  - Boundary violation #4 resolved: fields/ no longer imports useRecordObserver from model/
  - Boundary violation #8 resolved: search_model.js no longer imports UI dialog component
- [x] Phase 5: Fix Service/Component Inversion (2026-03-05)
  - Created: core/tree/ directory with 10 pure logic files:
    - 8 moved from components/tree_editor/: condition_tree.js, construct_tree_from_domain.js, construct_domain_from_tree.js, virtual_operators.js, utils.js, domain_from_tree.js, ast_utils.js, operators.js
    - 2 new extractions: in_range_options.js (from InRange component), operator_labels.js (from tree_editor_operator_editor.js)
  - Original files in components/tree_editor/ deleted (no shims — all consumers use canonical @web/core/tree/ paths)
  - tree_editor_operator_editor.js: stripped to only getOperatorEditorInfo (UI-coupled), imports pure logic from @web/core/tree/operator_labels
  - tree_editor_components.js: InRange.options now imports IN_RANGE_OPTIONS from @web/core/tree/in_range_options
  - tree_processor_service.js: all 7 component imports → 6 core/tree imports (InRange replaced by IN_RANGE_OPTIONS constant)
  - search_split_domain.js: domainFromTree import → @web/core/tree/domain_from_tree
  - Updated 8 web source files + 8 web test files + 6 tree_editor internal files + 4 spreadsheet/enterprise files + 4 addons_custom files + 1 mass_mailing JSDoc → canonical @web/core/tree/ paths
  - Boundary violation AP-03 resolved: services/ has 0 imports from @web/components/tree_editor/
  - Boundary violation AP-11 resolved: search/ has 0 imports from @web/components/tree_editor/
  - Result: `grep "from.*@web/components" services/` returns only debug menu dropdown (accepted)
  - Plan deviation: plan said "core/domain/" but core/domain.js exists as a file — used core/tree/ instead. Plan estimated 15 files; actual ~31 files due to no-shim approach (all consumers updated to canonical paths).

- [x] Phase 6a: Decompose SearchModel (2026-03-05)
  - Created: search/search_query_mutations.js (375 lines) — 12 exported + 2 private functions
    - Query mutation logic: addAutoCompletionValues, clearQuery, clearFilters, createNewFavorite, createIrFilters, createNewFilters, createNewGroupBy, deactivateGroup, toggleSearchItem, toggleDateFilter, toggleDateGroupBy, spawnCustomFilterDialog, switchGroupBySort
    - Private helpers: checkOrderByCountStatus, (createIrFilters also exported for wrapper)
  - Created: search/search_panel_state.js (295 lines) — 12 exported functions
    - Panel state logic: toggleCategoryValue, toggleFilterValues, clearSections, getSections, createCategoryTree, createFilterTree, ensureCategoryValue, fetchCategories, fetchFilters, fetchSections, reloadSections, shouldWaitForData
  - SearchModel: 1531 → 1045 lines (−486 lines, −32%)
  - Delegation pattern: standalone functions receive SearchModel as first arg, preserving subclass polymorphism (15 subclasses verified)
  - `_createIrFilters` wrapper kept on SearchModel for Knowledge module override compatibility
  - `_checkOrderByCountStatus` removed from class (private in query_mutations, never overridden)
  - Removed 6 imports from search_model.js (Domain, _t, rpcBus, getDefaultDomain, SPECIAL, etc.)
  - Namespace imports (`import * as queryMut/panelState`) for clean delegation with 24 thin wrappers
  - Plan deviation: plan estimated 3 files (~1050 total lines); actual: 3 files (1715 total lines due to JSDoc + delegation boilerplate). Net complexity reduction achieved — dense business logic separated from orchestrator.

- [x] Phase 6b: Decompose RelationalRecord (2026-03-05)
  - Created: model/relational_model/record_preprocessors.js (231 lines) — 7 exported functions
    - completeMany2OneValue, preprocessMany2oneChanges, preprocessMany2OneReferenceChanges, preprocessReferenceChanges, preprocessX2manyChanges, preprocessPropertiesChanges, preprocessHtmlChanges
  - Created: model/relational_model/record_save.js (192 lines) — 1 exported function
    - save: full persistence logic (web_save RPC, sendBeacon urgent saves, creation flow, reload)
  - RelationalRecord: 1378 → 1043 lines (−335 lines, −24%)
  - Delegation pattern: standalone functions receive record as first arg
  - No subclass overrides any extracted method (4 subclasses verified: ProjectTaskRecord, CalendarFormRecord, ProductCatalogRecord ×2)
  - `_save` wrapper kept on class (called from save/update/urgentSave via `this._save()`)
  - Preprocessor methods removed from class entirely — `_update` calls standalone functions directly
  - `_completeMany2OneValue` removed from class — only called by preprocessors (sibling calls in extracted module)
  - Removed 3 imports from record.js (markup, FetchRecordError, getFieldsSpec — exclusively used by extracted code)
  - Fixed retry callback: replaced `this._save(...arguments)` with explicit `save(record, { reload, onError, nextId })`
  - Updated enterprise/documents/static/src/views/documents_renderer_mixin.js — 4 preprocessor calls → standalone function imports

- [x] Phase 6c: action_service.js (SKIPPED — 2026-03-05)
  - Already well-decomposed: 8 files extracted (action_button_executor, action_info_builders, action_state, action_views, breadcrumb_manager, report_executor, action_dialog, skeleton_view)
  - Remaining 1,251 lines are cohesive closure-based core of the action manager
  - ControllerComponent (146 lines, inline class in _updateUI) is deeply coupled via closures to resolve/reject, dialog, controllerStack — extraction would add context-object indirection without reducing coupling
  - ~11% size reduction possible vs 24-32% in 6a/6b — poor benefit/complexity ratio

- [x] Phase 6d: Decompose StaticList (2026-03-05)
  - Created: model/relational_model/static_list_command_engine.js (275 lines) — 1 exported function
    - applyCommands: full x2many command processing (CREATE, UPDATE, DELETE, UNLINK, LINK)
  - Created: model/relational_model/static_list_sort.js (136 lines) — 3 exported functions
    - sort, resequence, sortBy
  - StaticList: 1217 → 868 lines (−349 lines, −29%)
  - No subclasses (0 found anywhere in codebase)
  - `_applyCommands` kept as thin wrapper (called externally from record.js, record_preprocessors.js, dynamic_list.js)
  - `_resequence`, `_sort`, `_sortBy` removed entirely from class — only called internally
  - Internal callers updated to use standalone functions directly
  - `sort` imported as `sortRecords` to avoid shadowing `sort` parameter in `_addRecord` method
  - Removed 5 imports from static_list.js (absorbUnlinkIntoSet, isUpdateRedundant, shouldEmitDelete, shouldEmitUnlink, compareRecords, computeNextOrderBy, pick)
  - No external consumer updates needed (all external callers use `_applyCommands` wrapper)

- [x] Phase 6e: properties_field.js (SKIPPED — 2026-03-05)
  - OWL Component (not a model/service class) — delegation pattern poorly suited
  - 5 methods patched/overridden by external modules: `checkDefinitionWriteAccess` (2 subclasses), `_getPropertyEditWarningText` (account_asset patch), `additionalPropertyDefinitionProps` + `onPropertyDefinitionChange` (ai_fields patch), `generatePropertyName` (test patch)
  - All event handlers deeply coupled to reactive state (`this.state`), props, services (`this.popover`, `this.notification`, `this.dialogService`), and DOM refs
  - Maximum extractable pure functions: ~86 lines (8% reduction) — well below productive threshold
  - Plan's `property_value_renderer.js` has no extraction target — rendering already handled by `PropertyValue` sub-component
  - Plan's `PropertyDefinitionManager` would be over-abstraction for ~42 lines of property management code

- [x] Phase 6f: Decompose GraphRenderer (2026-03-05)
  - Created: views/graph/graph_chart_config.js (502 lines) — 11 exported functions + constants
    - Chart data styling: styleBarChartData, styleLineChartData, stylePieChartData
    - Option builders: buildAnimationOptions, buildElementOptions, buildScaleOptions
    - Tooltip: buildTooltipItems
    - Legend generators: generatePieLegendLabels, generateBarLineLegendLabels
    - Utilities: gridOnTop (Chart.js plugin), getMaxWidth
    - Internal: formatValue, shortenLabel (not exported — only used by extracted code)
  - GraphRenderer: 974 → 557 lines (−417 lines, −43%)
  - 4 methods kept as thin wrappers (overridden by subclasses):
    - `getBarChartData()` — overridden by HrHolidaysGraphRenderer
    - `getLineChartData()` — overridden by StockForecastedGraphRenderer
    - `getScaleOptions()` — overridden by SkillsGraphRenderer, RecruitmentGraphRenderer
    - `getPieChartData()` — wrapper for consistency (not currently overridden)
  - 4 methods removed entirely from class:
    - `formatValue` — only called from extracted code (sibling calls)
    - `getAnimationOptions` → `buildAnimationOptions` (called directly in prepareOptions)
    - `getElementOptions` → `buildElementOptions` (called directly in prepareOptions)
    - `getTooltipItems` → `buildTooltipItems` (called directly in customTooltip)
  - `getLegendOptions` simplified: inline generateLabels callbacks → imported generators (63 → 22 lines)
  - Removed 8 imports from graph_renderer.js (cookie, colors/*, registry, sortBy, formatFloat, formatMonetary, SEP, markup)
  - Fixed preexisting bug: `"rgba(255,255,255,.15"` → `"rgba(255,255,255,.15)"` (missing closing paren)
  - Verified 8 subclasses + 1 patch: all use `super.method()` pattern, all work correctly with wrappers
  - No external consumer updates needed (all subclasses import only `GraphRenderer`)

- [x] Phase 6g: Decompose control_panel.js (SKIPPED — 2026-03-05)
  - OWL Component (805 lines) — same extractability issues as 6e
  - `EmbeddedActionsConfigHandler` (66 lines) already separate but too small for own file
  - All embedded action methods coupled to `this.state.embeddedInfos`, services, `env.searchModel`
  - Maximum extractable: ~12% (below productive threshold)

- [x] Phase 6h: Decompose sample_server.js (SKIPPED — 2026-03-05)
  - Non-component class (710 lines), already well-decomposed: sample_data.js + sample_field_generators.js extracted in Phase 3
  - Remaining methods are all `_mock*` RPC handlers forming cohesive unit around `this.data` and `this.existingGroups`
  - Every mock method reads/writes shared state — extraction would just move code between files without reducing coupling
  - `_aggregateFields` + `_formatValue` are pure-ish but only called by sibling `_mock*` methods (no external consumers)

- [x] Phase 6i: Decompose custom_color_picker.js (SKIPPED — 2026-03-05)
  - OWL Component (740 lines) — color conversion math already extracted to `@web/core/utils/format/colors`
  - Remaining code: 100% event handlers + state update methods
  - All methods coupled to `this.colorComponents`, 3 flags (`pickerFlag/sliderFlag/opacitySliderFlag`), 7 DOM refs, props callbacks
  - No subclasses or patches found — but nothing to extract (no pure logic remaining)

- [x] Phase 6j: Decompose datetime_field.js (SKIPPED — 2026-03-05)
  - `DateTimeField` component class is only 438 lines (below 500-line god object threshold)
  - Remaining 263 lines are declarative field registration configs (`dateField`, `dateTimeField`, `dateRangeField`) — static data, not extractable logic
  - Plan's `datetime_parser.js` suggestion incorrect — no parsing logic exists in file (parsing done by `@web/core/l10n/dates`)

## Phase 6 Summary
- **Executed**: 6a (SearchModel −32%), 6b (RelationalRecord −24%), 6d (StaticList −29%), 6f (GraphRenderer −43%)
- **Skipped**: 6c (action_service — already decomposed), 6e (properties_field — OWL), 6g (control_panel — OWL), 6h (sample_server — already decomposed), 6i (custom_color_picker — OWL), 6j (datetime_field — under threshold)
- **New files created**: 7 (search_query_mutations.js, search_panel_state.js, record_preprocessors.js, record_save.js, static_list_command_engine.js, static_list_sort.js, graph_chart_config.js)
- **Total lines extracted**: ~1,587 (375+295+231+192+275+136+502 — across 4 executed phases, not counting wrappers)
- **Total reduction in god objects**: SearchModel −486, RelationalRecord −335, StaticList −349, GraphRenderer −417 = **−1,587 lines**

- [x] Phase 7: Directory Restructure (2026-03-05 — reduced scope)
  - **Scope reduction**: Full FSD directory rename SKIPPED (core/→shared/, model/→entities/, etc.)
    - Would change every `@web/` import path — 500+ files across web, enterprise, addons_custom
    - Zero functional benefit: FSD is about dependency direction (already enforced by Phases 2-6), not naming conventions
    - Current directory names (core/, model/, fields/, views/, services/) are intuitive and well-understood
  - **Violation #5 re-assessed**: fields/ → model/ (getFieldDomain, getFieldContext) — **NOT a violation**
    - In FSD, features/ CAN import from entities/ — this is the correct direction
    - These functions live in model/ (entities layer) and are consumed by fields/ (features layer) — compliant
  - **Violation #7**: services/debug_menu → components/dropdown — ACCEPTED (Phase 1 decision, debug menu IS a UI component)
  - **Violation #9 RESOLVED**: search_query_mutations.js no longer imports from @web/components/
    - `getDefaultDomain` now injected into SearchModel via `with_search.js` (same DI pattern as DomainSelectorDialog)
    - Updated 3 files: with_search.js (+import +injection), search_model.js (+destructure +store), search_query_mutations.js (−import, use injected)
    - Zero enterprise/addon changes needed
  - **Result**: All 9 boundary violations now resolved or accepted:
    - #1 x2ManyCommands (Phase 2), #2 user singleton (Phase 3), #3 ORM class (Phase 3)
    - #4 useRecordObserver (Phase 4), #5 getFieldDomain (re-assessed: compliant)
    - #6 AP-03 service→component (Phase 5), #7 debug_menu (accepted)
    - #8 DomainSelectorDialog (Phase 4), #9 getDefaultDomain (Phase 7)
    - AP-11 search→component tree logic (Phase 5)
  - **index.js barrel exports**: DEFERRED — convention-only change with no functional impact

- [x] Phase 8: File Structure Cleanup (2026-03-05)
  - **Phase 8A: Dead Shim Removal — Settings & View Components**
    - Deleted 11 `webclient/settings_form_view/` shim files (all 3-line re-exports to `@web/views/settings/`)
    - Deleted 2 `views/view_components/` shim files (animated_number.js, column_progress.js → `@web/views/kanban/`)
    - Updated 4 consumer imports: 1 web test (settings_form_compiler), 1 crm test (AnimatedNumber), 2 mail src (ColumnProgress)
    - Removed entire `webclient/settings_form_view/` directory tree (5 dirs + 11 files)
    - 0 enterprise consumers existed — safe deletion
  - **Phase 8B: Action Hook Import Migration**
    - Deleted `search/action_hook.js` shim (re-exported 4 symbols from `@web/core/action_hook`)
    - Updated 43 consumer imports across entire repo:
      - 12 web source files (views/, webclient/)
      - 6 web test files
      - 19 enterprise files (web_gantt, knowledge, documents, account_reports, etc.)
      - 6 other core addon files (website, stock, web_hierarchy, spreadsheet_dashboard, product, mrp_mps)
    - All imports changed: `@web/search/action_hook` → `@web/core/action_hook`
  - **Phase 8C: Search Panel File Consolidation**
    - Moved `search_panel_fetch.js` and `search_panel_state.js` into existing `search_panel/` subdirectory
    - Updated 2 import paths: search_model.js (→ `./search_panel/search_panel_state`), search_panel_state.js (→ `../search_state`)
    - Updated `@module` JSDoc paths to reflect new locations
  - **Phase 8D: Misc Fixes**
    - Fixed incorrect `@deprecated` tag on `sortable_service.js` — has real consumers in website_slides
  - **Analysis conclusions (no action taken)**:
    - `core/utils/` flat structure is appropriate — 19 small diverse files don't cluster into 3+ groups
    - `search/` root structure is intentional — root = core logic (search_*), subdirs = UI components
    - `fields/` taxonomy well-organized, `views/` well-organized — no changes needed

- [x] Phase 9: Structured Error Hierarchy (2026-03-05)
  - Created: `NetworkError` base class in `core/network/rpc.js` (exported)
    - `RPCError`, `ConnectionLostError`, `ConnectionAbortedError` now extend `NetworkError`
    - Catch-by-category: `instanceof NetworkError` covers all RPC/connection failures
  - Wrapped `Domain.toList()` in `core/domain.js` to catch `EvaluationError` → re-throw as `InvalidDomainError`
    - Mirrors the existing constructor pattern (which already wraps `parseExpr` errors)
    - `EvaluationError` is now an implementation detail of the domain API, not part of the public contract
  - Simplified `domain_field.js`: removed `EvaluationError` import, collapsed dual `instanceof` check to single `instanceof InvalidDomainError`
  - State machine and typed event system remain deferred (no concrete motivation)

- [x] Phase 10: Complete core/tree/ Extraction (2026-03-05)
  - Moved 6 pure logic files from `components/tree_editor/` → `core/tree/`:
    - `construct_tree_from_expression.js` (276 lines) — Python expression → condition tree parser
    - `construct_expression_from_tree.js` (190 lines) — condition tree → Python expression builder
    - `domain_contains_expressions.js` (50 lines) — pure tree traversal (contains Expression check)
    - `tree_from_domain.js` (20 lines) — thin wrapper: domain → tree with virtual operators
    - `tree_from_expression.js` (19 lines) — thin wrapper: expression → tree with virtual operators
    - `expression_from_tree.js` (19 lines) — thin wrapper: tree → expression string
  - `core/tree/` grows from 10 → 16 files — full domain↔tree↔expression pipeline in one place
  - `components/tree_editor/` now purely OWL (8 files: 3 .js, 2 .xml, 1 .scss, 1 autocomplete, 1 value editor)
  - Consumer updates (no shims — all direct): 2 source files + 3 test files
    - `fields/specialized/domain/domain_field.js` — domainContainsExpressions → `@web/core/tree/`
    - `components/expression_editor/expression_editor.js` — expressionFromTree, treeFromExpression → `@web/core/tree/`
    - `tests/components/tree_editor/condition_tree.test.js` — 4 imports updated
    - `tests/components/tree_editor/tree_from_expression.test.js` — 1 import updated
    - `tests/components/tree_editor/expression_from_tree.test.js` — 1 import updated
  - Boundary violation resolved: `fields/domain_field.js` no longer imports from `@web/components/`
  - Zero enterprise/addon consumers existed — no external updates needed
  - **Test mirror structure restored**: 8 pure logic test files moved from `tests/components/tree_editor/` → `tests/core/tree/`
    - `between_operator.test.js`, `condition_tree.test.js`, `construct_domain_from_tree.test.js`,
      `construct_tree_from_domain.test.js`, `domain_from_tree.test.js`, `expression_from_tree.test.js`,
      `in_range_operator.test.js`, `tree_from_expression.test.js`
    - `construct_domain_from_tree.test.js`: inlined `formatDomain` (was `new Domain(str).toString()`) to eliminate helper dep
    - `tests/components/tree_editor/` now contains only `condition_tree_editor_test_helpers.js` (shared UI test fixture, 12 consumers across repo)

- [x] Phase 11: AP-09 Fix + Cleanup (2026-03-05)
  - **AP-09 resolved**: `ControllerComponent` hoisted from `_updateUI()` closure to `makeActionManager` scope
    - Was defined as a new class on every navigation (every `_updateUI` call); now defined once per manager
    - Per-call data (`controller`, `action`, `nextStack`, `resolve`, `reject`, `removeDialogRef`) passed via `this.props._context`
    - `componentProps` getter strips `_context` before passing props down to the child action component
    - Removed `static Component = controller.Component` (was per-instance per-call); replaced
      `this.constructor.Component !== View` checks with `this.Component` (instance property set in `setup()`)
    - `removeDialogFn?.()` in `onError` replaced with `removeDialogRef.current?.()` using a ref object
      to handle the timing: ref is populated after `dialog.add()` but before any `onError` fires
  - **Dead shim deleted**: `model/relational_model/record_hooks.js` had zero consumers (all 33 consumers
    already on `@web/fields/hooks/record_observer` from Phase 4 migration) — file removed
  - **Accepted coupling documented**: `services/install_scoped_app/install_scoped_app.js` → Dropdown
    — same pattern as `debug_menu*.js` (UI component living in services/ directory); both covered by ADR-003

## Not Started
  (none)

## Previously Planned — Now Resolved

### Phase 10: Complete core/tree/ Extraction (post-Phase 9 discovery)

**Discovery**: Post-Phase-9 codebase scan found 6 pure logic files still in `components/tree_editor/`
that Phase 5 missed. All 6 import only from `core/py_js/` and `core/tree/` — no OWL, no UI.

**Concrete violation**: `fields/specialized/domain/domain_field.js` imports `domainContainsExpressions`
from `@web/components/tree_editor/domain_contains_expressions` — a fields/ → components/ coupling.
Any future non-component code needing expression parsing must cross into the components/ layer.

**Files to move to `core/tree/`** (574 lines total):
- `construct_tree_from_expression.js` (276 lines) — Python expression → condition tree parser
- `construct_expression_from_tree.js` (190 lines) — condition tree → Python expression builder
- `domain_contains_expressions.js` (50 lines) — pure tree traversal (contains Expression check)
- `tree_from_domain.js` (20 lines) — thin wrapper: domain → tree with virtual operators
- `tree_from_expression.js` (19 lines) — thin wrapper: expression → tree with virtual operators
- `expression_from_tree.js` (19 lines) — thin wrapper: tree → expression string

**Consumer updates** (no shims — direct updates like Phase 5):
- `fields/specialized/domain/domain_field.js` (2 imports: domainContainsExpressions, treeFromDomain)
- `components/expression_editor/expression_editor.js` (1 import: treeFromExpression)
- `components/domain_selector/domain_selector.js` (1 import: treeFromDomain)
- `components/tree_editor/tree_editor.js` and siblings (internal cross-refs → absolute paths)
- Tests in `static/tests/components/tree_editor/`

**Accepted couplings (not targets for Phase 10)**:
- `with_search.js` → `getDefaultDomain` from `@web/components/domain_selector/utils` — accepted;
  `getDefaultDomain` depends on `getDomainDisplayedOperators` and `getDefaultValue` (both component-specific
  UI logic), so it cannot live in core/. Injection pattern in with_search.js is the best achievable.
- `debug_menu*.js` → `@web/components/dropdown/` — accepted (ADR-003, violation #7)
- `install_scoped_app.js` → `@web/components/dropdown/` — accepted (same as debug_menu; UI component in services/)
- `model/relational_model/record_hooks.js` → deleted (zero consumers, Phase 11)
- `search/` → `@web/services/user` — compliant (features layer uses shared services)

**Rejected — list_cell_helpers.js (REJ-004 partial)**:
REJ-004's "what to do instead" (~350 lines) was re-evaluated post-Phase-9. On close reading, the
candidate helpers (`getCellClass`, `getColumnClass`, `getRowClass`, `isSortable`) all access `this.*`
— component reactive state, props, cached values. The delegation pattern for OWL components (passing
`this` as first arg) adds complexity without reducing actual coupling. Effective pure functions are
~80 lines (`isSortable`, `isNumericColumn`). Benefit/complexity ratio is too low — DEFER indefinitely.

## Plan Deviations
- Phase 2: Plan listed `fields/parsers.js` as needing update — it does not import x2ManyCommands. Actual fields/ files updated: `fields/relational/x2many/x2many_field.js` and `fields/specialized/user_groups/res_user_group_ids_field.js` (8 total imports updated, matching plan count)
- Phase 3: Plan estimated 10 files and constructor injection. Actual: 3 files, no constructor changes. `current_company_id` was derivable from existing config data, and the `user` param to `buildSampleORM` was dead code. `Object.create(orm)` replaced `new ORM(user)` with cleaner prototype delegation.
- Phase 5: Plan said `core/domain/` — used `core/tree/` because `core/domain.js` already exists. Plan estimated 15 files changed with re-export shims; actual: ~31 files updated (no shims, all consumers on canonical paths). Plan listed 6 new files; actual: 10 (8 moved + 2 extractions: `in_range_options.js` and `operator_labels.js`).
- Phase 6a: Plan estimated ~450+250+350=1050 lines across 3 files; actual: 1045+375+295=1715 lines. Increase due to JSDoc on all standalone functions + delegation wrappers. `_createIrFilters` was made a wrapper (not removed) because Knowledge module overrides it. Used `import *` namespace pattern instead of individual `name as _name` aliases for cleaner imports.
- Phase 6b: Plan estimated record.js ~600 lines after extraction; actual: 1043 lines. Plan estimated ~200+200=400 lines in extractions; actual: 231+192=423 lines. Simpler than 6a: no subclass polymorphism concerns (0 overrides of extracted methods). Enterprise `documents` module called preprocessors directly on record instances — updated to use standalone functions (no shims). Used individual imports instead of `import *` (only 7 functions vs 24 in Phase 6a).
- Phase 6d: Plan estimated static_list.js ~650 lines; actual: 868. Plan estimated ~250+120=370 lines in extractions; actual: 275+136=411 lines. Cleanest extraction: 0 subclasses, 3 methods removed entirely (no wrappers), 1 method kept as thin wrapper. `sort` function renamed to `sortRecords` at import site to avoid shadowing local `sort` parameter in `_addRecord`. Included `_getCommands` serialization in static_list.js (stays) rather than extracting it — it delegates to `serializeCommands` already.
- Phase 6e: SKIPPED. Same reasoning as 6c — OWL Component methods deeply coupled to reactive state, services, and DOM refs. 5 methods patched/overridden externally. Max extraction: 8% (vs 24-43% in productive phases). Plan's suggested `property_value_renderer.js` and `PropertyDefinitionManager` don't match actual code structure.
- Phase 6f: Plan estimated graph_renderer.js ~500 lines + chart_config_builder.js ~400 lines. Actual: 557 + 502 = 1059 lines (vs 974 original). Increase due to JSDoc on standalone functions. Named file `graph_chart_config.js` instead of `chart_config_builder.js`. 4 wrappers kept (8 subclasses verified via super.method() calls), 4 methods removed entirely. formatValue and shortenLabel kept internal (not exported) — only used by extracted code. Best extraction ratio yet: 43% reduction.
- Phase 6g: SKIPPED. OWL Component — same reasoning as 6e. EmbeddedActionsConfigHandler already separate (66 lines) but too coupled to extract further.
- Phase 6h: SKIPPED. Non-component but already well-decomposed (sample_data.js + sample_field_generators.js extracted in Phase 3). Remaining `_mock*` methods form a cohesive RPC mocking unit around shared `this.data`/`this.existingGroups` state. Plan didn't account for prior extraction work.
- Phase 6i: SKIPPED. OWL Component — color conversion already extracted to `@web/core/utils/format/colors`. Remaining code is 100% event handlers + state update methods with 7 DOM refs and 3 flags. Plan's `color_math.js` suggestion was already done externally.
- Phase 6j: SKIPPED. Component class is only 438 lines (below 500-line threshold). 263 lines of declarative field registrations are static config data, not extractable logic. Plan's `datetime_parser.js` was incorrect — no parsing logic exists in file.
- Phase 7: SCOPE REDUCED. Plan called for full FSD directory rename (core/→shared/, model/→entities/, etc.) affecting 500+ files. Actual: 1 violation fix (#9 getDefaultDomain injection), 1 violation re-assessed (#5 is compliant), 0 directory renames. The plan assumed FSD required directory name changes — in practice, FSD is about dependency direction which Phases 2-6 already enforced. index.js barrel exports deferred as convention-only.
- Phase 8: Original plan (Phase 8 "New Abstractions") renumbered to Phase 9. Phase 8 repurposed for File Structure Cleanup based on fresh codebase-wide re-analysis. Key findings: (1) `core/utils/` flat structure is appropriate despite initial report calling it a "dumping ground" — 19 files are small and diverse, no natural 3+ clusters; (2) `search/` root structure is intentional — root = core logic extracted in Phase 6a, subdirs = UI components; (3) `sortable_service.js` was incorrectly marked `@deprecated` — has real consumers in `website_slides`; (4) 14 re-export shims found and removed (13 dead + 1 with 43 consumers migrated).

## Key Metrics
- Files analyzed: 612 (source) + 609 current (3 shim/dead file removals net)
- God objects (>500 lines): 38 original → 34 after Phase 6 splits
- Files to split: 10 original → 4 executed, 6 skipped (OWL components / already decomposed)
- Boundary violations: 9 original + 1 Phase 10 → 8 resolved, 3 accepted (debug_menu, install_scoped_app, with_search→getDefaultDomain), 0 pending
- Import paths updated (Phases 2-11): ~138 total (91 Phases 2-6b + 4 Phase 8A + 43 Phase 8B)
- Re-export shims removed: 15 (11 settings_form_view + 2 view_components + 1 action_hook + 1 record_hooks)
- Files moved: 2 (search_panel_fetch/state → search_panel/)
- Pure tree logic remaining in components/: 0 (Phase 10 complete)
- Dynamic class definitions inside functions: 0 (Phase 11 resolved AP-09)
- Directories removed: 1 tree (webclient/settings_form_view/ — 5 dirs)
- Custom error classes: 28 → 31 (Phase 9 added NetworkError, InvalidDomainError hierarchy)
- JSDoc coverage: 81% (494/612 files)
