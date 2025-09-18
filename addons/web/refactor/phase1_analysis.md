# Phase 1: Comprehensive Architecture Analysis

**Generated**: 2026-03-05
**Codebase**: Odoo 19.0 web module — 612 JS files, ~109K lines
**Session**: Claude Opus 4.6 (1M context) with extended thinking

---

## Table of Contents

1. [Deliverable 1: Dependency Graph Analysis](#deliverable-1)
2. [Deliverable 2: God Object Decomposition Plan](#deliverable-2)
3. [Deliverable 3: Directory Restructure Proposal](#deliverable-3)
4. [Deliverable 4: Abstraction Layer Proposals](#deliverable-4)
5. [Deliverable 5: Phased Execution Plan](#deliverable-5)
6. [Deliverable 6: Test Architecture Overhaul](#deliverable-6)
7. [Deliverable 7: Anti-Patterns Catalog](#deliverable-7)
8. [Machine-Parseable Sections](#machine-parseable)

---

<a id="deliverable-1"></a>
## Deliverable 1: Dependency Graph Analysis

### Directory Profiles

#### boot/
- **Layer**: infrastructure
- **Lines**: 80 | **Files**: 2
- **Inbound**: none (entry point only)
- **Outbound**: core (4), services (1), session (1), webclient (1)
- **Violations**: None — boot is the entry point, allowed to import from all layers
- **Coupling**: Low — fires once at startup

#### core/
- **Layer**: shared
- **Lines**: 16,944 | **Files**: 84
- **Inbound**: ALL directories import from core (1,130 total imports)
- **Outbound**: session (3) — only dependency
- **Violations**: None. VERIFIED: core imports nothing from components, fields, model, search, services, ui, views, or webclient
- **Coupling**: Low (pure utility, no upward deps) — hub by design

#### components/
- **Layer**: features
- **Lines**: 14,633 | **Files**: 87
- **Inbound**: fields (47), views (48), search (28), webclient (17), services (11), public (1), legacy (1), ui (1)
- **Outbound**: core (174), ui (17), services (8)
- **Violations**:
  - `services/ -> components/` (11 imports) — **LAYER INVERSION**: services should not import from components
    - `tree_processor_service.js` -> `tree_editor/*` (7 imports at lines 14-24)
    - `debug_menu.js` -> `dropdown/*` (2 imports)
    - `debug_menu_basic.js` -> `dropdown/*` (1 import)
    - `install_scoped_app/` -> `dropdown` (1 import)
- **Coupling**: Medium — widely consumed but imports are well-contained

#### fields/
- **Layer**: features
- **Lines**: 15,598 | **Files**: 109
- **Inbound**: views (24), components (0), search (0), webclient (1)
- **Outbound**: core (292), components (47), model (19), services (12), ui (11)
- **Violations**:
  - `fields/ -> model/` (19 imports) — **BOUNDARY CONCERN**: fields importing model internals
    - `useRecordObserver` (8 files): boolean_field, image_url_field, reference_field, ace_field, domain_field, json_checkboxes_field, properties_field, special_data — all from `record_hooks.js`
    - `getFieldDomain` (6 files): radio_field, selection_like_field, x2many_field, many2one_field, many2many_checkboxes, domain_field — from `utils.js` (barrel)
    - `getFieldContext` (2 files): field.js, many2one_field — from `utils.js` (barrel)
    - `x2ManyCommands` (1 file): parsers.js — from `orm_service.js` (via model barrel)
    - `extractFieldsFromArchInfo` (1 file): parsers.js — from `utils.js` (barrel)
    - `Record` class (1 file): user_groups — from `record.js`
- **Coupling**: Medium — the 19 model imports are the primary concern

#### model/
- **Layer**: entities
- **Lines**: 8,537 | **Files**: 29
- **Inbound**: fields (19), views (38), search (1), webclient (0)
- **Outbound**: core (49), services (9)
- **Violations**:
  - `model/ -> services/` (9 imports) — **DEPENDENCY DIRECTION**: model importing service-layer constants
    - `x2ManyCommands` (7 files): static_list, static_list_utils, command_builder, field_values, dynamic_list, record, relational_model — from `orm_service.js`
    - `user` singleton (2 files): model.js, field_context.js — from `services/user.js`
    - `ORM` class (1 file): sample_server.js — from `orm_service.js`
  - VERIFIED: model does NOT import UI (dialogs, notifications, components). The model UI hooks pattern (`makeModelUIHooks()`) enforces this boundary correctly.
- **Coupling**: Medium — the `x2ManyCommands` coupling is structural but fixable

#### search/
- **Layer**: features (with widget characteristics)
- **Lines**: 7,152 | **Files**: 30
- **Inbound**: views (52), webclient (4)
- **Outbound**: core (71), components (28), model (1), services (6), ui (1), session (1)
- **Violations**:
  - `search_model.js` imports `DomainSelectorDialog` from `@web/components/domain_selector_dialog` — **NEWLY DISCOVERED**: a model/data class importing a UI dialog component. This is used for the "Edit domain" action in favorites.
  - `search_model.js` imports `getDefaultDomain` from `@web/components/domain_selector/utils` — logic function in wrong layer
  - `search_split_domain.js` imports `domainFromTree` from `@web/components/tree_editor/domain_from_tree` — logic function in wrong layer
- **Coupling**: Medium — mostly consumes components (expected for UI-rich search)

#### services/
- **Layer**: shared (infrastructure)
- **Lines**: 5,472 | **Files**: 31
- **Inbound**: components (8), model (9), fields (12), views (22), webclient (24), search (6), ui (4)
- **Outbound**: core (96), components (11), session (3), ui (2)
- **Violations**:
  - `services/ -> components/` (11 imports) — **LAYER INVERSION** (see components/ profile above)
  - `services/ <-> ui/` — bidirectional: services imports ui (2), ui imports services (4)
- **Coupling**: Medium — services are consumed by all upper layers (expected)

#### ui/
- **Layer**: shared (primitives)
- **Lines**: 2,566 | **Files**: 20
- **Inbound**: components (17), fields (11), views (30), search (1), services (2), webclient (2)
- **Outbound**: core (38), services (4), components (1)
- **Violations**:
  - `ui/ -> components/` (1 import) — minor, likely for a specific component type
  - `ui/ <-> services/` bidirectional — shared state between ui_service and ui primitives
- **Coupling**: Low — mostly consumed, few outbound deps

#### views/
- **Layer**: features (with widget characteristics)
- **Lines**: 26,543 | **Files**: 141
- **Inbound**: webclient (14), search (0)
- **Outbound**: core (276), components (48), fields (24), model (38), search (52), services (22), ui (30), session (5)
- **Coupling**: High — consumes from 8 other directories. This is expected: views are the highest composition layer before webclient.
- **Violations**: None at the structural level. The `settings/` subdirectory imports from `form/` — this is expected inheritance.

#### webclient/
- **Layer**: pages
- **Lines**: 6,392 | **Files**: 56
- **Inbound**: boot (1)
- **Outbound**: core (104), components (17), fields (1), search (4), services (24), ui (2), views (14), session (6)
- **Violations**: None — as the page layer, webclient is allowed to import from all lower layers
- **Coupling**: High (expected for page layer)

#### public/
- **Layer**: pages (standalone)
- **Lines**: 1,868 | **Files**: 11
- **Inbound**: none
- **Outbound**: core (15), components (1)
- **Violations**: None
- **Coupling**: Low — isolated public pages

#### legacy/
- **Layer**: deprecated
- **Lines**: 1,976 | **Files**: 6
- **Inbound**: none from modern code
- **Outbound**: core (11), components (1)
- **Violations**: None worth fixing — targeted for removal
- **Coupling**: Low

### Proposed Layer Assignment

```
CURRENT DIRECTORY    → TARGET FSD LAYER   → RATIONALE
─────────────────────────────────────────────────────
core/                → shared/             Utility foundation (pure, no Odoo domain knowledge)
services/            → shared/             Infrastructure services (DI container)
ui/                  → shared/             UI primitives (dialog, popover, tooltip — no domain)
session.js           → shared/             Session singleton

model/               → entities/           Core data types (Record, List, Group, DataPoint)
                                           x2ManyCommands belongs here

fields/              → features/           Self-contained field widget features
components/          → features/           Reusable UI features (domain_selector, tree_editor, emoji)
search/              → features/           Search feature (control panel, search bar, search model)
views/               → features/           View type features (list, form, kanban, etc.)

webclient/           → pages/              Full page compositions
public/              → pages/              Public pages (colibri, interaction)

boot/                → infrastructure/     Entry point
legacy/              → infrastructure/     Deprecated bridge code
```

### Violation Resolution Plan

| # | Violation | Resolution | Phase |
|---|-----------|-----------|-------|
| 1 | `model/ -> services/orm_service` (x2ManyCommands, 7 files) | Move `x2ManyCommands` to `model/relational_model/commands.js`, re-export from `orm_service.js` for backward compat | 2 |
| 2 | `model/ -> services/user` (user singleton, 2 files) | Inject `user` via constructor/params instead of direct import | 3 |
| 3 | `model/ -> services/orm_service` (ORM class in sample_server) | Inject ORM via constructor parameter | 3 |
| 4 | `fields/ -> model/record_hooks` (useRecordObserver, 8 files) | Move `useRecordObserver` to `fields/hooks/` — it's a field-layer hook that depends on record reactivity, not model internals | 4 |
| 5 | `fields/ -> model/utils` (getFieldDomain, getFieldContext, 8 files) | Extract domain/context resolution to `fields/field_domain.js` that receives record data via props | 4 |
| 6 | `services/tree_processor_service -> components/tree_editor/*` (7 imports) | Extract the pure logic functions from `tree_editor/` into `core/domain/` or `core/tree/` — the service should import from shared, not features | 5 |
| 7 | `services/debug_menu -> components/dropdown` (3 imports) | Accept — debug menu IS a component, it's registered as a service for DI reasons but renders dropdown UI. Consider moving to `webclient/debug/` | 5 |
| 8 | `search_model.js -> components/domain_selector_dialog` | Inject dialog spawning via callback/hook instead of direct import | 4 |
| 9 | `search_model.js -> components/domain_selector/utils` | Move `getDefaultDomain` to `core/domain/` — it's pure logic | 5 |

### Dependency Diagram — Current State

```
                            ┌─────────┐
                            │  boot   │
                            └────┬────┘
                                 │
    ┌─────────────────────────── │ ──────────────────────────────┐
    │                            ▼                               │
    │                      ┌──────────┐                          │
    │           ┌──────────│   core   │──────────┐               │
    │           │          └──────────┘          │               │
    │           │               ▲                │               │
    │           ▼               │                ▼               │
    │     ┌──────────┐   ┌─────┴─────┐   ┌──────────┐          │
    │     │ services │◄──│    ui     │──►│ session  │          │
    │     └────┬─────┘   └──────────┘   └──────────┘          │
    │          │  ▲                                              │
    │          │  │ ◄── VIOLATION (11 imports)                   │
    │          ▼  │                                              │
    │  ┌────────────────┐      ┌──────────┐                     │
    │  │  components    │◄─────│  fields  │──► model (19)       │
    │  └───────┬────────┘      └────┬─────┘                     │
    │          │                    │                            │
    │          ▼                    ▼                            │
    │  ┌────────────┐       ┌──────────┐                        │
    │  │   search   │◄──────│  views   │────────────────┐       │
    │  └────────────┘       └────┬─────┘                │       │
    │                            │                      │       │
    │                            ▼                      ▼       │
    │                      ┌──────────┐          ┌──────────┐   │
    │                      │webclient │          │  model   │   │
    │                      └──────────┘          └──────────┘   │
    │                                                           │
    └───────────────────────────────────────────────────────────┘
```

### Dependency Diagram — Target State

```
    ┌──────────── SHARED LAYER ─────────────────────┐
    │ core/  services/  ui/  session                 │
    │ (imports only within layer or from OWL/libs)   │
    └─────────────────────┬─────────────────────────┘
                          │
    ┌──────────── ENTITIES LAYER ───────────────────┐
    │ model/  (Record, List, Group, DataPoint)       │
    │ x2ManyCommands, field_context, eval_context    │
    │ (imports from shared/ only)                    │
    └─────────────────────┬─────────────────────────┘
                          │
    ┌──────────── FEATURES LAYER ───────────────────┐
    │ fields/  components/  search/  views/          │
    │ (imports from shared/ and entities/)            │
    │ (NO cross-feature imports except via registry) │
    └─────────────────────┬─────────────────────────┘
                          │
    ┌──────────── PAGES LAYER ──────────────────────┐
    │ webclient/  public/                            │
    │ (imports from any lower layer)                 │
    └───────────────────────────────────────────────┘
```

---

<a id="deliverable-2"></a>
## Deliverable 2: God Object Decomposition Plan

### 1. list_renderer.js (1,543 lines, views/list/)

**Responsibilities**:
1. Component wiring / setup — lines 137-387 (250 lines)
2. Column management — lines 395-653 (260 lines)
3. Cell/row rendering helpers — lines 459-908 (450 lines)
4. Group layout delegation — lines 950-1030 (80 lines)
5. Inline editing — lines 431-445, 557-579, 1067-1121
6. Keyboard navigation — delegated to `useListKeyboardNavigation`
7. Checkbox selection — delegated to `useListSelection`
8. Drag-and-drop — lines 291-308, 1471-1527
9. Column sorting — lines 695-748
10. Optional fields — delegated to `useListOptionalFields`

**DECISION: KEEP TOGETHER (with caveat)**

Despite being the largest file, `ListRenderer` has already been significantly decomposed through hooks:
- `useListKeyboardNavigation` — separate file
- `useListSelection` — separate file
- `useListOptionalFields` — separate file
- `useListVirtualization` — separate file
- `useListAggregates` — separate file
- `useMagicColumnWidths` — separate file
- `list_grid_state.js` — separate file
- `list_group_layout.js` — separate file
- `list_column_utils.js` — separate file

The 1,543 lines are mostly the OWL component wiring and rendering getter methods. OWL's single-`setup()` contract means the component IS the aggregation point. However, one extraction is worth doing:

**Proposed extraction**: `ListCellHelpers` — pure rendering helper functions (lines 459-908, ~450 lines)

| New File | Lines (est.) | Key Exports | Depends On |
|----------|-------------|-------------|------------|
| `list_cell_helpers.js` | ~350 | `getFieldProps`, `getCellClass`, `getCellTitle`, `getFormattedValue`, `getColumnClass`, `getRowClass`, `evalInvisible`, `evalColumnInvisible`, `makeTooltip` | `core/utils/decorations`, `core/py_js/py` |

**Risk**: Low — pure functions, no state
**Public API Impact**: None external — these are only used by the renderer template

### 2. search_model.js (1,530 lines, search/)

**Responsibilities**:
1. Lifecycle / bootstrap — lines 98-311 (213 lines)
2. Query mutation (toggle filters/groupbys) — lines 435-862 (427 lines)
3. Favorites management — lines 486-520, delegated to `search_favorites.js`
4. Search panel sections — lines 686-725, 921-1129 (247 lines)
5. Domain/context/groupBy/orderBy computation — lines 340-420, 1151-1389 (290 lines)
6. Search items lifecycle — lines 554-591, 884-985
7. State import/export — lines 614-618
8. Properties support — lines 863-880, delegated to `search_properties.js`

**DECISION: SPLIT**

**Proposed Split**:

| New File | Lines (est.) | Key Exports | Depends On |
|----------|-------------|-------------|------------|
| `search_model.js` | ~450 | `SearchModel` (orchestrator) | all below |
| `search_panel_state.js` | ~250 | `SearchPanelState` | orm, search_panel_fetch |
| `search_query_mutations.js` | ~350 | `createNewFilters`, `deactivateGroup`, `toggleSearchItem`, etc. | search_state, search_items |

**Shared State**: `searchItems` map and `query` array must be shared between orchestrator and mutations module. Pass via constructor reference.
**Public API Impact**: `SearchModel` class remains the public API — internal delegation is invisible to consumers.
**Risk**: Medium — `SearchModel` is used by ~52 view imports and ~4 search imports. The external API must remain identical.

### 3. record.js (1,378 lines, model/relational_model/)

**Responsibilities**:
1. Setup / initialization — lines 54-100
2. Core state getters — lines 134-175
3. Public mutation API (lifecycle) — lines 180-341
4. Save / persist — lines 1016-1182 (166 lines, most complex single method)
5. Change tracking and application — lines 360-441
6. Server value parsing — lines 796-853
7. Change pre-processing (6 parallel preprocessors) — lines 855-990 (135 lines)
8. Onchange — lines 1280-1319
9. Update orchestration — lines 1321-1377
10. Validation — lines 443-487
11. Eval context — lines 1190-1208
12. Archive/delete/duplicate — lines 181-247
13. Properties handling — lines 728-791

**DECISION: SPLIT**

| New File | Lines (est.) | Key Exports | Depends On |
|----------|-------------|-------------|------------|
| `record.js` | ~600 | `RelationalRecord` (core class) | record_save, record_preprocessors |
| `record_save.js` | ~200 | `saveRecord`, `urgentSaveRecord` | orm_service, record_validator |
| `record_preprocessors.js` | ~200 | `preprocessMany2one`, `preprocessX2many`, `preprocessProperties`, etc. | field_values, field_context |

**Shared State**: The preprocessors need `this.fields`, `this.data`, `this.model` — pass as parameters.
**Public API Impact**: `RelationalRecord` remains the export. Save and preprocessing become private helpers.
**Risk**: Medium — `record.js` is the core data node, used by `static_list.js`, `relational_model.js`, and all field widgets.

### 4. action_service.js (1,251 lines, webclient/actions/)

**Responsibilities**:
1. Controller stack management — lines 134-160, 404-434
2. Action loading / preprocessing — lines 246-342
3. `_updateUI` + ControllerComponent — lines 478-768 (290 lines!)
4. Action-type executors — lines 770-985
5. Dialog management — lines 186-195, 674-703
6. URL/state/breadcrumbs — lines 142-174, 1172-1224
7. Public navigation API — lines 991-1161

**DECISION: SPLIT**

Already partially decomposed: `action_button_executor.js`, `action_info_builders.js`, `action_state.js`, `action_views.js`, `breadcrumb_manager.js`, `report_executor.js`, `action_dialog.js`, `skeleton_view.js`.

| New File | Lines (est.) | Key Exports | Depends On |
|----------|-------------|-------------|------------|
| `action_service.js` | ~500 | `makeActionManager`, `actionService` | all below |
| `controller_component.js` | ~180 | `ControllerComponent` | OWL, CallbackRecorder |
| `url_state_manager.js` | ~100 | `loadState`, `pushState` | router |

**Shared State**: `controllerStack`, `dialog`, `nextDialog` — passed as reactive references.
**Public API Impact**: `actionService` remains the export. `ControllerComponent` extraction is invisible.
**Risk**: Medium — `_updateUI` dynamically defines `ControllerComponent` inline. Extracting it requires careful closure handling.

### 5. static_list.js (1,217 lines, model/relational_model/)

**Responsibilities**:
1. Setup / initialization — lines 37-64
2. Getters — lines 68-103
3. Public mutation API — lines 123-461
4. Command log management — lines 568-807 (240 lines)
5. Record datapoint creation — lines 815-930
6. Save-point / discard — lines 557-566, 937-960
7. Dialog record extension — lines 234-343 (110 lines)
8. Pagination / loading — lines 400-411, 1051-1075
9. Sorting / resequencing — lines 1107-1208

**DECISION: SPLIT**

| New File | Lines (est.) | Key Exports | Depends On |
|----------|-------------|-------------|------------|
| `static_list.js` | ~650 | `StaticList` | command_engine, static_list_sort |
| `static_list_command_engine.js` | ~250 | `applyCommands`, `clearCommands` | command_builder |
| `static_list_sort.js` | ~120 | `sortRecords`, `resequenceRecords` | static_list_utils |

**Shared State**: `_cache`, `_currentIds`, `_commands` — passed as references.
**Public API Impact**: `StaticList` remains the export.
**Risk**: Low — command engine is self-contained; sorting reads from cache.

### 6. properties_field.js (1,095 lines, fields/specialized/properties/)

**Responsibilities**:
1. Component setup — lines 1-90
2. Property definition CRUD — lines 150-350
3. Drag-and-drop reordering — lines 350-450
4. Property value rendering — lines 450-650
5. Separator/section management — lines 650-750
6. Dialog spawning — lines 750-900
7. Property tags display — lines 900-1095

**DECISION: SPLIT**

| New File | Lines (est.) | Key Exports | Depends On |
|----------|-------------|-------------|------------|
| `properties_field.js` | ~500 | `PropertiesField` | property_definition_manager |
| `property_definition_manager.js` | ~350 | `PropertyDefinitionManager` | orm |
| `property_value_renderer.js` | ~250 | rendering helpers | formatters |

**Risk**: Medium — complex internal state sharing between definition CRUD and rendering.

### 7. pivot_model.js (1,037 lines, views/pivot/)

**DECISION: KEEP TOGETHER**

The PivotModel is a specialized data processing class that transforms flat RPC data into a pivot table matrix. Its internal state is deeply interleaved: header groups, measure cells, sort state, and fold/unfold tracking all reference each other. The cohesion is high.

**Justification**: Line count is high but all methods serve the single responsibility of pivot-table state management. Splitting would create excessive parameter passing of the internal data structures (`rowGroupTree`, `colGroupTree`, `cells`, `headers`).

### 8. calendar_model.js (1,020 lines, views/calendar/)

**DECISION: KEEP TOGETHER**

Similar to PivotModel — a specialized view model with deeply interleaved state: date range, event records, filters, and quick-create logic all depend on the same reactive state.

**Justification**: High cohesion. The model manages a single concern (calendar view state) with all methods focused on date navigation, event CRUD, and filter management.

### 9. graph_renderer.js (974 lines, views/graph/)

**DECISION: SPLIT**

| New File | Lines (est.) | Key Exports | Depends On |
|----------|-------------|-------------|------------|
| `graph_renderer.js` | ~500 | `GraphRenderer` | chart_config_builder |
| `chart_config_builder.js` | ~400 | `buildChartConfig`, `buildTooltip`, `buildLegend` | Chart.js |

**Risk**: Low — Chart.js configuration building is pure functional code.

### 10. relational_model.js (934 lines, model/relational_model/)

**DECISION: KEEP TOGETHER**

`RelationalModel` is the top-level orchestrator for the ORM data layer. It creates records/lists/groups, manages the RPC mutex, handles onchange, and coordinates loading. Its responsibilities are cohesive around a single concern: managing a data graph. The private `_load` methods form a family that shouldn't be split.

### 11. draggable_hook_builder.js (868 lines, core/utils/dnd/)

**DECISION: KEEP TOGETHER**

This is a builder pattern that constructs a drag-and-drop hook. The builder's state machine (drag start, drag move, drag end, cleanup) is a single concern. The line count reflects the complexity of DOM event handling across mouse and touch.

### 12. control_panel.js (805 lines, search/control_panel/)

**DECISION: SPLIT**

| New File | Lines (est.) | Key Exports | Depends On |
|----------|-------------|-------------|------------|
| `control_panel.js` | ~450 | `ControlPanel` | control_panel_buttons, control_panel_search |
| `control_panel_buttons.js` | ~200 | button rendering helpers | — |
| `control_panel_search_menu.js` | ~150 | search menu wiring | — |

**Risk**: Low — UI composition splitting.

### 13. kanban_renderer.js (781 lines, views/kanban/)

**DECISION: KEEP TOGETHER**

Already uses hooks (`useDropdown`, `useSortable`, `useService`). The rendering logic is tightly integrated with the kanban card/column visual model. No clear independent concern to extract without creating excessive coupling.

### 14. search_bar.js (779 lines, search/search_bar/)

**DECISION: KEEP TOGETHER**

The search bar manages autocomplete, token rendering, and keyboard navigation as a single interactive component. Already imports from siblings for specialized behavior.

### 15. form_compiler.js (760 lines, views/form/)

**DECISION: KEEP TOGETHER**

A clean visitor pattern. Each `compile*` method handles one XML element type. Despite the line count, the pattern is consistent and cohesive. The only notable complexity is `compileGroup` (172 lines) which handles inner/outer group distinction.

**Justification**: Splitting by element type would create 12+ tiny files with no independent testability.

### 16. custom_color_picker.js (740 lines, components/color_picker/)

**DECISION: SPLIT**

| New File | Lines (est.) | Key Exports | Depends On |
|----------|-------------|-------------|------------|
| `custom_color_picker.js` | ~400 | `CustomColorPicker` | color_math |
| `color_math.js` | ~340 | `hslToRgb`, `rgbToHsl`, `parseColor`, etc. | — |

**Risk**: Low — pure math functions.

### 17. emoji_picker.js (728 lines, components/emoji_picker/)

**DECISION: KEEP TOGETHER**

A single interactive component managing emoji search, grid rendering, skin tone selection, and recent emoji tracking. Cohesive around one feature.

### 18. datetime_picker.js (712 lines, components/datetime/)

**DECISION: KEEP TOGETHER**

Calendar widget with month/year navigation, date range selection, and time input. Cohesive single-feature component.

### 19. datetime_field.js (701 lines, fields/temporal/datetime/)

**DECISION: SPLIT**

| New File | Lines (est.) | Key Exports | Depends On |
|----------|-------------|-------------|------------|
| `datetime_field.js` | ~400 | `DateTimeField` | datetime_parser |
| `datetime_parser.js` | ~300 | parsing/formatting helpers | luxon |

**Risk**: Low — parsing logic is pure functional.

### 20. form_controller.js (690 lines, views/form/)

**DECISION: KEEP TOGETHER**

Already well-structured. The cog menu concern (86 lines) is the only notable sub-concern, but it's too small to justify extraction.

### 21-38. Remaining files (501-630 lines)

For files 501-630 lines, applying the decision framework:

| File | Lines | Decision | Rationale |
|------|-------|----------|-----------|
| many2x_autocomplete.js | 630 | KEEP | Single interactive component |
| datetime_picker_service.js | 620 | KEEP | Service with clear lifecycle |
| field.js | 586 | KEEP | Generic field resolver — cohesive |
| dynamic_list.js | 585 | KEEP | List state management — cohesive |
| colibri.js | 577 | KEEP | Public page widget — isolated |
| tree_processor_service.js | 576 | KEEP | Already well-decomposed into closures |
| graph_model.js | 572 | KEEP | Specialized view model |
| list_controller.js | 560 | KEEP | Already uses hooks for decomposition |
| clickbot.js | 557 | KEEP | Test utility — not production code |
| py_date.js | 552 | KEEP | Pure date computation library |
| list_keyboard_nav.js | 549 | KEEP | Single hook concern |
| autocomplete.js | 531 | KEEP | Single interactive component |
| view.js | 525 | KEEP | Generic view loader — cohesive |
| export_data_dialog.js | 513 | KEEP | Single dialog component |
| py_interpreter.js | 507 | KEEP | Interpreter — cohesive state machine |
| debug_items.js | 501 | KEEP | Collection of menu items |
| sample_server.js | 708 | SPLIT | See below |

**sample_server.js (708 lines)** — SPLIT:

| New File | Lines (est.) | Key Exports | Depends On |
|----------|-------------|-------------|------------|
| `sample_server.js` | ~350 | `buildSampleORM` | sample_data_generators |
| `sample_data_generators.js` | ~350 | `generateSampleValue` per type | — |

**Risk**: Low — data generators are pure functions.

---

<a id="deliverable-3"></a>
## Deliverable 3: Directory Restructure Proposal

### Priority 1: Zero-Addon-Impact Moves (Internal Only)

#### Move Group: x2ManyCommands to model/
PHASE: 2
RISK: Low
ADDON_IMPACT: 0 (addons import from `@web/services/orm_service` for ORM class, not commands)

```
- OLD: services/orm_service.js (exports x2ManyCommands)
  NEW: model/relational_model/commands.js (new file)
  REASON: Pure constant that defines x2many command protocol — belongs with model
  IMPORT_UPDATES: 8 (7 model/ files + 1 fields/ file) — plus re-export shim in orm_service.js
```

Migration: Add `export { x2ManyCommands } from "@web/model/relational_model/commands"` re-export in orm_service.js for backward compat.

#### Move Group: Pure Tree Logic to core/
PHASE: 5
RISK: Low
ADDON_IMPACT: 0

```
- OLD: components/tree_editor/condition_tree.js
  NEW: core/domain/condition_tree.js
  REASON: Pure data structures — no UI, no OWL
  IMPORT_UPDATES: ~12

- OLD: components/tree_editor/construct_tree_from_domain.js
  NEW: core/domain/construct_tree_from_domain.js
  REASON: Pure domain-to-tree conversion
  IMPORT_UPDATES: ~4

- OLD: components/tree_editor/utils.js
  NEW: core/domain/tree_utils.js
  REASON: Pure utility functions
  IMPORT_UPDATES: ~8

- OLD: components/tree_editor/virtual_operators.js
  NEW: core/domain/virtual_operators.js
  REASON: Pure operator definitions
  IMPORT_UPDATES: ~4

- OLD: components/domain_selector/utils.js
  NEW: core/domain/domain_defaults.js
  REASON: getDefaultDomain is pure logic
  IMPORT_UPDATES: ~3
```

Migration script concept:
```bash
find core/addons/ -name "*.js" -exec sed -i \
  's|@web/components/tree_editor/condition_tree|@web/core/domain/condition_tree|g' {} +
```

#### Move Group: useRecordObserver to fields/
PHASE: 4
RISK: Low
ADDON_IMPACT: 0 (no addons import this directly)

```
- OLD: model/relational_model/record_hooks.js
  NEW: fields/hooks/record_observer.js
  REASON: Hook designed for field components — belongs with fields
  IMPORT_UPDATES: 10 (8 fields + 1 views/kanban + 1 search)
```

### Priority 2: Low-Addon-Impact Moves (1-2 Imports)

#### Move Group: UPDATE_METHODS constant
PHASE: 2
RISK: Low
ADDON_IMPACT: 1

```
- OLD: services/orm_service.js (exports UPDATE_METHODS)
  NEW: model/constants.js
  REASON: Defines which ORM methods trigger data changes — model concern
  IMPORT_UPDATES: 3
```

### Priority 3: Module Boundary Enforcement (index.js files)

PHASE: 1
RISK: Low
ADDON_IMPACT: 0

Add `index.js` barrel exports to every directory with 3+ files:

```
NEW: core/index.js
NEW: components/index.js
NEW: fields/index.js
NEW: model/index.js
NEW: model/relational_model/index.js
NEW: search/index.js
NEW: services/index.js
NEW: ui/index.js
NEW: views/index.js
NEW: webclient/index.js
```

These define the public API surface. Internal files (not in index.js) should be prefixed with `_` over time.

**NOTE**: This does NOT change any import paths. It establishes the convention for future phases. Existing direct imports continue to work — index.js adds an ADDITIONAL import path, not a replacement.

### Full FSD Restructure (Phase 7 — Future)

The full directory restructure to FSD layers is deferred to Phase 7. The intermediate phases (2-6) fix violations and decompose god objects within the current directory structure. Phase 7 moves entire directories.

The full restructure is documented in the machine-parseable section below.

---

<a id="deliverable-4"></a>
## Deliverable 4: Abstraction Layer Proposals

### 1. Record Observer Pattern — APPROVED

**Problem**: 8 field components + 1 view component directly import `useRecordObserver` from `model/relational_model/record_hooks.js`, creating fields→model coupling. The hook depends on OWL reactivity (`effect()`) and record props, not model internals.

**Concrete examples**:
- `fields/basic/boolean/boolean_field.js:10` — imports useRecordObserver
- `fields/specialized/domain/domain_field.js:17` — imports useRecordObserver
- `fields/specialized/properties/properties_field.js:22` — imports useRecordObserver
- (8 total files)

**Interface**:
```js
// fields/hooks/record_observer.js (moved from model/)
import { effect } from "@web/core/utils/reactive";
import { Deferred } from "@web/core/utils/concurrency";

/**
 * Observe record value changes in a field component.
 * @param {(record: any, props?: any) => void | Promise<void>} callback
 */
export function useRecordObserver(callback) { /* ... existing implementation ... */ }
```

**Replaces**: Direct import from `@web/model/relational_model/record_hooks`
**Migration**: Move file, update 10 import paths, add re-export shim in old location
**Justification**: The hook uses `effect()` from `core/utils/reactive` and reads from `props.record` — it has NO dependency on model internals. It belongs with fields.

### 2. x2Many Command Constants — APPROVED

**Problem**: 7 model files import `x2ManyCommands` from `services/orm_service.js`, creating model→services coupling. The constant is a pure enum with no runtime dependency on the ORM service.

**Concrete examples**:
- `model/relational_model/record.js:7`
- `model/relational_model/static_list.js` (import)
- `model/relational_model/command_builder.js` (import)
- `model/relational_model/field_values.js` (import)
- `model/relational_model/dynamic_list.js` (import)
- (7 total)

**Interface**:
```js
// model/relational_model/commands.js
export const x2ManyCommands = {
    CREATE: 0, create(virtualID, values) { /* ... */ },
    UPDATE: 1, update(id, values) { /* ... */ },
    DELETE: 2, delete(id) { /* ... */ },
    UNLINK: 3, unlink(id) { /* ... */ },
    LINK: 4,   link(id) { /* ... */ },
    CLEAR: 5,  clear() { /* ... */ },
    SET: 6,    set(ids) { /* ... */ },
};
```

**Replaces**: Import from `@web/services/orm_service`
**Migration**: Move constant, update 8 imports, add re-export in `orm_service.js`
**Justification**: Pure constant with zero service dependency.

### 3. Domain Tree Logic Extraction — APPROVED

**Problem**: `tree_processor_service.js` imports 7 items from `components/tree_editor/*`, creating a service→component layer inversion. The imported items are pure logic functions (no OWL components), but they live in the wrong layer.

**Concrete examples**:
- `services/tree_processor_service.js:14-24` — 7 imports from tree_editor
- `search/search_split_domain.js:12` — imports from tree_editor
- `search/search_model.js:6` — imports from domain_selector

**Interface**:
```js
// core/domain/ (new directory)
// - condition_tree.js — condition(), Expression, isTree, normalizeValue
// - construct_tree_from_domain.js — constructTreeFromDomain()
// - tree_utils.js — disambiguate, getResModel, isId
// - virtual_operators.js — introduceVirtualOperators()
// - domain_from_tree.js — domainFromTree()
// - domain_defaults.js — getDefaultDomain()
```

**Replaces**: Imports from `@web/components/tree_editor/*` and `@web/components/domain_selector/utils`
**Migration**: Move 6 files, update ~30 import paths, add re-export shims
**Justification**: These are pure domain/tree data structures with zero UI dependency.

### 4. State Machine for Form Save — DEFERRED (See rejected.md)

**Problem**: The form save flow (CLEAN→DIRTY→VALIDATING→SAVING→RELOADING→CLEAN) is implicit in `record.js`. Transitions are serialized through `model.mutex.exec()`.

**Evidence**: Only 1 file (`record.js`) — the implicit state machine is already functional and mutex-serialized. Adding an explicit state machine would add complexity without solving a real bug.

**Decision**: DEFERRED to Phase 8. Log in rejected.md for now.

### 5. Typed Event System — DEFERRED

**Problem**: Events use string constants from `core/events.js`. Already partially typed.

**Evidence**: `core/events.js` already defines `AppEvent`, `RpcEvent`, `RouterEvent` as constant objects. The pattern is established but not universally adopted.

**Decision**: DEFERRED. The existing pattern is functional. A full typed event system (using TypeScript or JSDoc generics) would require broader TS adoption first.

### 6. Structured Error Hierarchy — DEFERRED

**Problem**: 28 custom error classes exist but are scattered across files with no base class hierarchy.

**Evidence**: `RPCError`, `ConnectionLostError`, `ConnectionAbortedError`, `InvalidDomainError`, `KeyNotFoundError`, `ViewNotFoundError`, `FetchRecordError`, `ParserError`, `CalendarParseArchError`, etc.

**Decision**: DEFERRED to Phase 8. The errors work correctly today. A unified hierarchy would be valuable for error handling/reporting but is not blocking.

### 7. Plugin System — NOT APPLICABLE

**Problem Statement**: Formalize the extension mechanism for fields, views, and actions.

**Analysis**: The registry pattern IS the plugin system. `fieldRegistry`, `viewRegistry`, `actionRegistry`, `serviceRegistry` already provide:
- Registration: `registry.category("fields").add("boolean", { component: BooleanField })`
- Discovery: `registry.category("fields").get("boolean")`
- Extension: `registry.category("fields").add("my_boolean", { ...base, component: MyBooleanField })`
- Validation: `registry.addValidation(schema)`

**Decision**: REJECTED. See rejected.md REJ-001.

---

<a id="deliverable-5"></a>
## Deliverable 5: Phased Execution Plan

### Phase 1: Foundation — Low Risk

**Goal**: Add module boundary conventions (index.js) and JSDoc types without any behavioral change.
**Prerequisites**: None
**Duration estimate**: S (10-15 files created)

**Changes**:

| # | Change | Files Touched | Import Updates | Risk |
|---|--------|--------------|---------------|------|
| 1 | Add index.js to each top-level directory | 10 new files | 0 | Low |
| 2 | Add JSDoc @typedef for cross-module data structures | ~20 files | 0 | Low |
| 3 | Document all 28 error classes in a single error_catalog.md | 1 new file | 0 | Low |

**Verification**:
- [ ] All existing tests pass (no behavioral change)
- [ ] `ruff` linting passes (JS linting: `eslint`)
- [ ] No new imports added — only new files

**Rollback**: Delete index.js files and JSDoc additions.

### Phase 2: Constants & Types — Low Risk

**Goal**: Move `x2ManyCommands` and `UPDATE_METHODS` to model layer. Zero behavioral change.
**Prerequisites**: Phase 1
**Duration estimate**: S (5 files changed)

**Changes**:

| # | Change | Files Touched | Import Updates | Risk |
|---|--------|--------------|---------------|------|
| 1 | Create `model/relational_model/commands.js` with `x2ManyCommands` | 1 new | 0 | Low |
| 2 | Update 7 model/ files to import from new location | 7 | 7 | Low |
| 3 | Add re-export in `orm_service.js` for backward compat | 1 | 0 | Low |
| 4 | Update `fields/parsers.js` to import from new location | 1 | 1 | Low |

**Verification**:
- [ ] `grep -r "x2ManyCommands" --include="*.js"` shows no broken imports
- [ ] All model/ and fields/ tests pass
- [ ] Addons that import x2ManyCommands from orm_service still work (re-export shim)

**Rollback**: Revert the 10 file changes.

### Phase 2 Session — Load List (~8K tokens)

```
### Source files to load:
core/addons/web/static/src/services/orm_service.js
core/addons/web/static/src/model/relational_model/static_list.js
core/addons/web/static/src/model/relational_model/static_list_utils.js
core/addons/web/static/src/model/relational_model/command_builder.js
core/addons/web/static/src/model/relational_model/field_values.js
core/addons/web/static/src/model/relational_model/dynamic_list.js
core/addons/web/static/src/model/relational_model/record.js
core/addons/web/static/src/model/model.js
core/addons/web/static/src/fields/parsers.js

### Context files to load (read-only):
core/addons/web/refactor/REFACTOR_STATE.md
core/addons/web/refactor/phase1_analysis.md (Section: Phase 2)
core/addons/web/refactor/decisions.md

### Tests to run after changes:
--test-tags /web (full web module tests)
```

### Phase 3: Decouple Model Layer — Medium Risk

**Goal**: Remove all service imports from model/. Inject user and ORM via constructor parameters.
**Prerequisites**: Phase 2
**Duration estimate**: M (10 files changed)

**Changes**:

| # | Change | Files Touched | Import Updates | Risk |
|---|--------|--------------|---------------|------|
| 1 | Add `user` param to `Model` constructor | 2 | 2 | Medium |
| 2 | Thread `user` through `RelationalModel` to `field_context.js` | 3 | 3 | Medium |
| 3 | Inject ORM into `sample_server.js` via param | 2 | 2 | Low |
| 4 | Remove direct `import { user }` from model files | 2 | 2 | Low |

**Verification**:
- [ ] `grep -r "from.*@web/services" model/` returns 0 results
- [ ] All model/ tests pass
- [ ] Form, list, kanban views all function correctly

**Rollback**: Revert model/ changes, restore direct imports.

### Phase 3 Session — Load List (~20K tokens)

```
### Source files to load:
core/addons/web/static/src/model/model.js
core/addons/web/static/src/model/relational_model/relational_model.js
core/addons/web/static/src/model/relational_model/field_context.js
core/addons/web/static/src/model/sample_server.js
core/addons/web/static/src/services/user.js
core/addons/web/static/src/services/orm_service.js
core/addons/web/static/src/views/view.js (to see how Model is constructed)

### Tests to run:
--test-tags /web
```

### Phase 4: Decouple Fields from Model — Medium Risk

**Goal**: Move `useRecordObserver` to fields layer. Extract field domain/context resolution.
**Prerequisites**: Phase 3
**Duration estimate**: M (15 files changed)

**Changes**:

| # | Change | Files Touched | Import Updates | Risk |
|---|--------|--------------|---------------|------|
| 1 | Move `record_hooks.js` to `fields/hooks/record_observer.js` | 1 moved | 10 | Medium |
| 2 | Add re-export shim in old location | 1 | 0 | Low |
| 3 | Update 8 field files to import from new location | 8 | 8 | Low |
| 4 | Refactor search_model to inject DomainSelectorDialog | 1 | 1 | Medium |

**Verification**:
- [ ] `grep -r "from.*@web/model" fields/` shows only `getFieldDomain`/`getFieldContext` (to be addressed in Phase 7)
- [ ] All fields/ and search/ tests pass

### Phase 5: Fix Service/Component Inversion — Medium Risk

**Goal**: Extract pure tree logic from components/ to core/domain/.
**Prerequisites**: Phase 4
**Duration estimate**: M (15 files changed)

**Changes**:

| # | Change | Files Touched | Import Updates | Risk |
|---|--------|--------------|---------------|------|
| 1 | Create `core/domain/` with pure tree logic | 6 new | 0 | Low |
| 2 | Update `tree_processor_service.js` imports | 1 | 7 | Medium |
| 3 | Update `search_split_domain.js` imports | 1 | 1 | Low |
| 4 | Update `components/tree_editor/` to import from core/domain/ | ~10 | ~20 | Medium |
| 5 | Add re-export shims in old component locations | 6 | 0 | Low |

**Verification**:
- [ ] `grep -r "from.*@web/components" services/` returns only debug menu dropdown imports (accepted)
- [ ] All search/ and domain-related tests pass

### Phase 6: Decompose God Objects — Medium Risk

**Goal**: Split files identified in Deliverable 2 as SPLIT candidates.
**Prerequisites**: Phase 5
**Duration estimate**: L (15+ files changed, one PR per split)

**Sub-phases** (one PR each):

| # | Split | Source Lines | New Files | Risk |
|---|-------|------------|-----------|------|
| 6a | `search_model.js` → 3 files | 1,530 | 2 new | Medium |
| 6b | `record.js` → 3 files | 1,378 | 2 new | Medium |
| 6c | `action_service.js` → 3 files | 1,251 | 2 new | Medium |
| 6d | `static_list.js` → 3 files | 1,217 | 2 new | Low |
| 6e | `properties_field.js` → 3 files | 1,095 | 2 new | Medium |
| 6f | `graph_renderer.js` → 2 files | 974 | 1 new | Low |
| 6g | `control_panel.js` → 3 files | 805 | 2 new | Low |
| 6h | `sample_server.js` → 2 files | 708 | 1 new | Low |
| 6i | `custom_color_picker.js` → 2 files | 740 | 1 new | Low |
| 6j | `datetime_field.js` → 2 files | 701 | 1 new | Low |

### Phase 7: Directory Restructure — High Risk

**Goal**: Move files to FSD layout.
**Prerequisites**: Phase 6
**Duration estimate**: L (100+ import path updates)

This phase should be executed AFTER all splitting is done, to minimize the number of times import paths change.

### Phase 8: New Abstractions — Low Risk

**Goal**: Add state machines, typed errors, and event system improvements.
**Prerequisites**: Phase 7
**Duration estimate**: M

This phase is additive — new code, not refactoring.

---

<a id="deliverable-6"></a>
## Deliverable 6: Test Architecture Overhaul

### 6a. Test Tagging Strategy

Proposed tag taxonomy:

```
@model      — model/ tests (Record, StaticList, DynamicList, RelationalModel)
@field      — fields/ tests (individual field widgets)
@view-list  — views/list/ tests
@view-form  — views/form/ tests
@view-kanban — views/kanban/ tests
@view-calendar — views/calendar/ tests
@view-pivot — views/pivot/ tests
@view-graph — views/graph/ tests
@search     — search/ tests (SearchModel, control panel, search bar)
@webclient  — webclient/ tests (action service, navbar, settings)
@core       — core/ tests (domain, py_js, utils, registry)
@component  — components/ tests (tree_editor, autocomplete, datetime)
@smoke      — Critical path smoke tests (~30s subset)
@regression — Full regression suite
```

Assignment rule: Each test file gets the tag matching its source directory. Monster test files that test across boundaries get multiple tags.

### 6b. Monster Test File Decomposition

| Test File | Lines | Proposed Splits | Grouping | Est. Tests/Split |
|-----------|-------|----------------|----------|-----------------|
| list_view.test.js | 20,234 | list_render.test, list_edit.test, list_group.test, list_keyboard.test, list_selection.test, list_sort.test | By feature concern | ~50 each |
| kanban_view.test.js | 15,456 | kanban_render.test, kanban_drag.test, kanban_quick_create.test, kanban_progressive.test | By interaction type | ~60 each |
| one2many_field.test.js | 14,049 | o2m_basic.test, o2m_commands.test, o2m_dialog.test, o2m_nested.test | By operation type | ~40 each |
| form_view.test.js | 13,583 | form_render.test, form_save.test, form_buttons.test, form_notebook.test | By UI section | ~50 each |
| calendar_view.test.js | 6,231 | calendar_render.test, calendar_nav.test, calendar_crud.test | By interaction | ~30 each |
| many2one_field.test.js | 4,278 | m2o_autocomplete.test, m2o_dialog.test | By interaction | ~40 each |
| pivot_view.test.js | 4,169 | pivot_render.test, pivot_drill.test | By feature | ~30 each |

### 6c. Mock Server Unification

**Modern system** (`_framework/mock_server/`): Uses `mock_model.js` (4,098 lines) — defines MockModel with full ORM simulation.

**Legacy system** (`legacy/helpers/mock_server.js`, 2,587 lines): Older pattern, used by some older tests.

**Recommendation**: The modern mock server survives. The legacy mock server should be migrated incrementally as legacy tests are updated.

**Reducing mock_model.js (4,098 lines)**: Split into:
- `mock_model_crud.js` — create/read/update/unlink (~1,500 lines)
- `mock_model_search.js` — search/read_group/name_search (~1,200 lines)
- `mock_model_fields.js` — field type simulation (~800 lines)
- `mock_model.js` — orchestrator (~600 lines)

### 6d. Test Performance Optimization

Top 5 slow patterns:
1. **Full view rendering for simple model tests** — many tests render an entire form/list view when they only need to test model behavior. Convert to unit tests using `MockModel` directly.
2. **Redundant mock server setup** — each test re-creates the mock environment. Shared fixtures per test suite would reduce setup time.
3. **DOM-heavy assertions** — tests that query many DOM elements. Use structured data assertions where possible.
4. **Unnecessary waitFor** — some tests use arbitrary timeouts. Replace with proper async assertions.
5. **Large mock datasets** — some tests define 50+ records when 3-5 would suffice.

### 6e. Test-Source Colocation

| Criterion | Colocated | Mirror Structure (current) |
|-----------|-----------|---------------------------|
| Discovery | Better — test is right next to source | Requires mental path mapping |
| Bundle size | Needs explicit exclusion from production bundles | Naturally excluded (different directory) |
| Git history | Cleaner — source+test change together | Split across directories |
| CI isolation | Harder to run "only tests" | Easy: `static/tests/` glob |
| Odoo convention | Not standard | Standard Odoo pattern |

**Recommendation**: Keep mirror structure (current). Odoo's asset bundling system includes files by glob pattern — colocating tests would require adding exclusion rules to every bundle definition.

---

<a id="deliverable-7"></a>
## Deliverable 7: Anti-Patterns Catalog

### AP-01: No Module Boundaries — Priority: Critical

**Where**: All 612 JS files — ZERO index.js files exist
**Problem**: Every file's exports are individually importable. There is no public API surface defined for any directory. Any refactoring that changes a file's export signature is a potential breaking change for all consumers.
**Fix**: Add index.js barrel exports to each directory (Phase 1). Over time, mark non-public files with `_` prefix.
**Effort**: S (Phase 1)

### AP-02: God Objects — Priority: High

**Where**: 38 files over 500 lines (see Deliverable 2)
**Problem**: Large files with multiple responsibilities are harder to test, review, and maintain.
**Fix**: Split 10 files identified as SPLIT candidates (Phase 6).
**Effort**: L (Phase 6, one PR per file)

### AP-03: Layer Inversion: Service → Component — Priority: High

**Where**: `services/tree_processor_service.js:14-24` — 7 imports from `components/tree_editor/`
**Problem**: Services are a lower layer than components. A service depending on component internals means the component cannot be removed/refactored without affecting the service.
**Fix**: Extract pure tree logic to `core/domain/` (Phase 5).
**Effort**: M

### AP-04: Misplaced Constants — Priority: Medium

**Where**: `services/orm_service.js:31-69` — `x2ManyCommands` constant
**Problem**: A pure constant defined in a service file, creating false coupling from model→services.
**Fix**: Move to `model/relational_model/commands.js` (Phase 2).
**Effort**: S

### AP-05: Singleton User Import — Priority: Medium

**Where**: `model/model.js:18`, `model/relational_model/field_context.js`
**Problem**: `user` is a module-level singleton imported directly, bypassing DI. Makes model testing without the user service impossible.
**Fix**: Inject via constructor parameter (Phase 3).
**Effort**: S

### AP-06: UI Import in Data Class — Priority: Medium

**Where**: `search/search_model.js:7` — imports `DomainSelectorDialog` (a UI dialog component)
**Problem**: `SearchModel` is a data/state class that should not know about UI dialog components. This import means SearchModel cannot be tested without the dialog component loaded.
**Fix**: Inject dialog spawning via callback (Phase 4).
**Effort**: S

### AP-07: Scattered Error Types — Priority: Low

**Where**: 28 custom error classes across 20+ files
**Problem**: No common base class, no centralized error catalog. Error handling code must know about each specific error class to handle it.
**Fix**: Document in error_catalog.md (Phase 1), optionally create error hierarchy (Phase 8).
**Effort**: S (catalog) / M (hierarchy)

### AP-08: Inconsistent State Patterns — Priority: Low

**Where**: 4 reactive patterns: `useState` (106 files), `reactive()` (20), `extends Reactive` (2), `markRaw` (11)
**Problem**: Developers must choose between 4 patterns for reactivity. New code may use the wrong pattern.
**Fix**: Already documented in machine_doc_v1/STATE_MANAGEMENT.md with clear decision tree. Enforce via code review. No code change needed.
**Effort**: None

### AP-09: Dynamic Inner Class Definition — Priority: Low

**Where**: `webclient/actions/action_service.js:528-673` — `ControllerComponent` defined inside `_updateUI()`
**Problem**: A 145-line OWL component class is defined dynamically inside a function. Makes the component un-importable, un-testable, and un-extendable.
**Fix**: Extract to `controller_component.js` (Phase 6c).
**Effort**: S

### AP-10: Implicit State Machine in Record Save — Priority: Low

**Where**: `model/relational_model/record.js` — save flow (CLEAN→DIRTY→VALIDATING→SAVING→RELOADING→CLEAN)
**Problem**: State transitions are implicit, serialized through mutex. Hard to trace the current state.
**Fix**: Deferred to Phase 8 — the mutex pattern works correctly today.
**Effort**: M

### AP-11: search_model Imports Component-Layer Logic — Priority: Medium

**Where**: `search/search_split_domain.js:12` — `domainFromTree` from `components/tree_editor/`
**Problem**: Search layer depending on component-layer module for pure logic.
**Fix**: Move `domainFromTree` to `core/domain/` (Phase 5).
**Effort**: S

---

<a id="machine-parseable"></a>
## Machine-Parseable Sections

### Section A: File Move Registry

```yaml
## File Moves

### Move Group: x2ManyCommands to model/
PHASE: 2
RISK: Low
ADDON_IMPACT: 0

- OLD: services/orm_service.js (export x2ManyCommands — keep re-export)
  NEW: model/relational_model/commands.js
  UPDATES: 8

### Move Group: useRecordObserver to fields/
PHASE: 4
RISK: Low
ADDON_IMPACT: 0

- OLD: model/relational_model/record_hooks.js
  NEW: fields/hooks/record_observer.js
  UPDATES: 10

### Move Group: Pure Tree Logic to core/domain/
PHASE: 5
RISK: Low
ADDON_IMPACT: 0

- OLD: components/tree_editor/condition_tree.js
  NEW: core/domain/condition_tree.js
  UPDATES: 12

- OLD: components/tree_editor/construct_tree_from_domain.js
  NEW: core/domain/construct_tree_from_domain.js
  UPDATES: 4

- OLD: components/tree_editor/utils.js
  NEW: core/domain/tree_utils.js
  UPDATES: 8

- OLD: components/tree_editor/virtual_operators.js
  NEW: core/domain/virtual_operators.js
  UPDATES: 4

- OLD: components/tree_editor/domain_from_tree.js
  NEW: core/domain/domain_from_tree.js
  UPDATES: 3

- OLD: components/domain_selector/utils.js
  NEW: core/domain/domain_defaults.js
  UPDATES: 3
```

### Section B: Split Registry

```yaml
## File Splits

### Split: search_model.js (1530 lines)
PHASE: 6a
RISK: Medium

- NEW: search/search_model.js (~450 lines) — core orchestrator
  EXPORTS: SearchModel
  METHODS: constructor, setup, load, reload, _notify, domain (getter), context (getter), groupBy (getter), orderBy (getter), facets (getter), exportState, _importState

- NEW: search/search_panel_state.js (~250 lines)
  EXPORTS: SearchPanelState
  METHODS: _createCategoryTree, _createFilterTree, _fetchCategories, _fetchFilters, _fetchSections, _reloadSections, _shouldWaitForData, _ensureCategoryValue, toggleCategoryValue, toggleFilterValues, clearSections, getSections
  SHARED_STATE: sections (Map), searchPanelInfo (passed via constructor)

- NEW: search/search_query_mutations.js (~350 lines)
  EXPORTS: createNewFilters, deactivateGroup, toggleSearchItem, toggleDateFilter, toggleDateGroupBy, switchGroupBySort, addAutoCompletionValues, clearQuery, clearFilters, createNewGroupBy
  SHARED_STATE: searchItems, query, nextId, nextGroupId (passed as context object)

### Split: record.js (1378 lines)
PHASE: 6b
RISK: Medium

- NEW: model/relational_model/record.js (~600 lines) — core class
  EXPORTS: RelationalRecord
  METHODS: setup, _setData, _applyChanges, _applyValues, _setEvalContext, _checkValidity, archive, unarchive, delete, duplicate, load, save, urgentSave, update, discard, switchMode, isDirty, getChanges

- NEW: model/relational_model/record_save.js (~200 lines)
  EXPORTS: saveRecord, urgentSaveRecord
  METHODS: _save (full method), sendBeacon path
  SHARED_STATE: model, config, _values, _changes (passed as parameters)

- NEW: model/relational_model/record_preprocessors.js (~200 lines)
  EXPORTS: preprocessMany2one, preprocessX2many, preprocessProperties, preprocessHtml, preprocessMany2oneReference, preprocessReference
  SHARED_STATE: fields, data (passed as parameters)

### Split: action_service.js (1251 lines)
PHASE: 6c
RISK: Medium

- NEW: webclient/actions/action_service.js (~500 lines) — main service
  EXPORTS: makeActionManager, actionService, clearUncommittedChanges
  METHODS: doAction, doActionButton, switchView, restore, _loadAction, _preprocessAction, _updateUI (trimmed), action executors

- NEW: webclient/actions/controller_component.js (~180 lines)
  EXPORTS: ControllerComponent
  METHODS: setup, getLocalState, getGlobalState, beforeLeave, beforeUnload

- NEW: webclient/actions/url_state_manager.js (~100 lines)
  EXPORTS: loadState, pushState, openActionInNewWindow
  SHARED_STATE: controllerStack (passed as reference)

### Split: static_list.js (1217 lines)
PHASE: 6d
RISK: Low

- NEW: model/relational_model/static_list.js (~650 lines) — core class
  EXPORTS: StaticList

- NEW: model/relational_model/static_list_command_engine.js (~250 lines)
  EXPORTS: applyCommands, applyInitialCommands, clearCommands
  SHARED_STATE: _cache, _currentIds, _commands (passed as context)

- NEW: model/relational_model/static_list_sort.js (~120 lines)
  EXPORTS: sortRecords, resequenceRecords
  SHARED_STATE: _cache, config.orderBy (passed as parameters)

### Split: graph_renderer.js (974 lines)
PHASE: 6f
RISK: Low

- NEW: views/graph/graph_renderer.js (~500 lines) — OWL component
  EXPORTS: GraphRenderer

- NEW: views/graph/chart_config_builder.js (~400 lines)
  EXPORTS: buildChartConfig, buildTooltip, buildLegend, buildScales
  SHARED_STATE: none (pure functions)

### Split: sample_server.js (708 lines)
PHASE: 6h
RISK: Low

- NEW: model/sample_server.js (~350 lines)
  EXPORTS: buildSampleORM

- NEW: model/sample_data_generators.js (~350 lines)
  EXPORTS: generateSampleValue, SAMPLE_GENERATORS
  SHARED_STATE: none (pure functions)
```

### Section C: Phase-Specific File Lists

```yaml
## Phase 1 Session — Load List (~5K tokens)
### Files to create:
core/addons/web/static/src/core/index.js
core/addons/web/static/src/components/index.js
core/addons/web/static/src/fields/index.js
core/addons/web/static/src/model/index.js
core/addons/web/static/src/model/relational_model/index.js
core/addons/web/static/src/search/index.js
core/addons/web/static/src/services/index.js
core/addons/web/static/src/ui/index.js
core/addons/web/static/src/views/index.js
core/addons/web/static/src/webclient/index.js

### No source files need loading — only new file creation

## Phase 2 Session — Load List (~15K tokens)
### Source files to load:
core/addons/web/static/src/services/orm_service.js
core/addons/web/static/src/model/relational_model/static_list.js
core/addons/web/static/src/model/relational_model/static_list_utils.js
core/addons/web/static/src/model/relational_model/command_builder.js
core/addons/web/static/src/model/relational_model/field_values.js
core/addons/web/static/src/model/relational_model/dynamic_list.js
core/addons/web/static/src/model/relational_model/record.js
core/addons/web/static/src/model/model.js
core/addons/web/static/src/fields/parsers.js

### Context files:
core/addons/web/refactor/REFACTOR_STATE.md
core/addons/web/refactor/decisions.md

### Tests to run:
--test-tags /web

## Phase 3 Session — Load List (~20K tokens)
### Source files to load:
core/addons/web/static/src/model/model.js
core/addons/web/static/src/model/relational_model/relational_model.js
core/addons/web/static/src/model/relational_model/field_context.js
core/addons/web/static/src/model/sample_server.js
core/addons/web/static/src/services/user.js
core/addons/web/static/src/services/orm_service.js
core/addons/web/static/src/views/view.js

### Tests to run:
--test-tags /web

## Phase 4 Session — Load List (~25K tokens)
### Source files to load:
core/addons/web/static/src/model/relational_model/record_hooks.js
core/addons/web/static/src/fields/basic/boolean/boolean_field.js
core/addons/web/static/src/fields/media/image_url/image_url_field.js
core/addons/web/static/src/fields/relational/reference/reference_field.js
core/addons/web/static/src/fields/specialized/ace/ace_field.js
core/addons/web/static/src/fields/specialized/domain/domain_field.js
core/addons/web/static/src/fields/basic/json_checkboxes/json_checkboxes_field.js
core/addons/web/static/src/fields/specialized/properties/properties_field.js
core/addons/web/static/src/fields/relational/special_data.js
core/addons/web/static/src/search/search_model.js
core/addons/web/static/src/views/kanban/kanban_record.js

### Tests to run:
--test-tags /web

## Phase 5 Session — Load List (~30K tokens)
### Source files to load:
core/addons/web/static/src/services/tree_processor_service.js
core/addons/web/static/src/components/tree_editor/condition_tree.js
core/addons/web/static/src/components/tree_editor/construct_tree_from_domain.js
core/addons/web/static/src/components/tree_editor/utils.js
core/addons/web/static/src/components/tree_editor/virtual_operators.js
core/addons/web/static/src/components/tree_editor/tree_editor_components.js
core/addons/web/static/src/components/tree_editor/tree_editor_operator_editor.js
core/addons/web/static/src/components/tree_editor/domain_from_tree.js
core/addons/web/static/src/components/domain_selector/utils.js
core/addons/web/static/src/search/search_split_domain.js
core/addons/web/static/src/search/search_model.js

### Tests to run:
--test-tags /web

## Phase 6a Session — Load List (~40K tokens)
### Source files to load:
core/addons/web/static/src/search/search_model.js (full, 1530 lines)
core/addons/web/static/src/search/search_arch_parser.js
core/addons/web/static/src/search/search_context.js
core/addons/web/static/src/search/search_domain.js
core/addons/web/static/src/search/search_enrichment.js
core/addons/web/static/src/search/search_facets.js
core/addons/web/static/src/search/search_favorites.js
core/addons/web/static/src/search/search_group_by.js
core/addons/web/static/src/search/search_panel_fetch.js
core/addons/web/static/src/search/search_properties.js
core/addons/web/static/src/search/search_split_domain.js
core/addons/web/static/src/search/search_state.js

### Tests to run:
--test-tags @search
```
