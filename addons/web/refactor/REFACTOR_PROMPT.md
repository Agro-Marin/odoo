# Web Module JS Architecture Refactoring — 1M Context + Extended Thinking

## Session Configuration

This prompt is designed for a Claude session with:
- **1M token context window** (load all JS source in a single session)
- **Extended thinking enabled** ("ultrathink" / max thinking budget)

The JS source alone (~1.07M tokens without emoji_data.js) nearly fills context. Tests (2.2M tokens) require separate sessions.

### Token Budget

| Content | Tokens (est.) | Phase |
|---------|--------------|-------|
| This prompt + machine docs + architecture docs | ~80K | All |
| All JS source (612 files, excl. emoji_data.js) | ~1,070K | 1 |
| XML templates (260 files) | ~154K | 2 |
| JS tests (382 files, 234K lines) | ~2,200K | 3+ |
| SCSS (197 files) | ~118K | Optional |

---

## Extended Thinking Strategy

You have a large thinking budget. Use it deliberately, not just for streaming output. Structure your thinking in these phases:

### Thinking Phase 1: Mental Model Construction (~20% of thinking)

Before writing ANY output, build a mental model in your thinking:

1. **Read the dependency matrix** (provided below) and internalize which directories are leaves (no inbound deps from peers) vs hubs (everything depends on them).
2. **Identify the actual layer hierarchy** from the import data — not what we wish it was, but what it IS today.
3. **For each god object** (files >500 lines), mentally trace: what are the distinct state groups? Which methods touch which state? Where are the natural seam lines?
4. **Map the service dependency graph**: which services depend on which other services? What's the initialization order?

### Thinking Phase 2: Validation & Cross-Referencing (~15% of thinking)

Before committing to recommendations:

1. **Cross-reference** every proposed file move against the addon impact data below. If `addons_custom/` imports a path, the cost of moving it is higher.
2. **Verify boundary violations** by checking the ACTUAL imports (provided below), not assumed violations. The original analysis had some claims that turned out to be wrong.
3. **Check for hidden coupling**: files that don't import each other directly but share state through a service or registry.
4. **Validate each proposed split** by asking: "Can I write a test for module A without importing module B?" If not, the split is wrong.

### Thinking Phase 3: Trade-off Analysis (~15% of thinking)

For each major recommendation, explicitly reason about:

1. **Migration cost**: How many files need import path updates? (Use the import counts below.)
2. **Risk of behavioral change**: Does the refactor change any runtime behavior, even subtly?
3. **Reversibility**: If this change turns out wrong, how hard is it to undo?
4. **Sequencing dependencies**: Which changes MUST come before others?

### Thinking Phase 4: Output Generation (~50% of thinking)

Only now write the deliverables, grounded in the validated mental model.

---

## Context Loading Instructions

In your 1M context session, load files in this exact order:

### Step 1: Architecture docs (load first — ~80K tokens)

```
core/addons/web/machine_doc_v1/ARCHITECTURE.md
core/addons/web/machine_doc_v1/DIRECTORY_MAP.md
core/addons/web/machine_doc_v1/JS_FILE_INDEX.md
core/addons/web/machine_doc_v1/STATE_MANAGEMENT.md
core/addons/web/machine_doc_v1/CONVENTIONS.md
core/addons/web/machine_doc_v1/PERFORMANCE.md
core/addons/web/machine_doc_v1/MODEL_MAP.md
core/addons/web/doc/COMPONENT_DIAGRAM.md
core/addons/web/doc/FLOW_DIAGRAM.md
```

### Step 2: All JS source files (~1,070K tokens)

Load every `.js` file under `core/addons/web/static/src/` EXCEPT `emoji_data.js` (36K lines of generated data). Use this command to generate the file list:

```bash
find core/addons/web/static/src -name "*.js" ! -name "emoji_data.js" | sort
```

### Step 3: Manifest (asset bundle definitions)

```
core/addons/web/__manifest__.py
```

---

## Pre-Computed Data

This data was extracted from the codebase to save your thinking budget. Use it as ground truth — do not re-derive these numbers from source.

### Directory-Level Statistics

| Directory | Files | Lines | % of Total | Role |
|-----------|-------|-------|-----------|------|
| views/ | 141 | 26,543 | 24.4% | View types (list, form, kanban, calendar, pivot, graph, etc.) |
| core/ | 84 | 16,944 | 15.6% | Framework utilities (registry, utils, domain, py_js, l10n) |
| fields/ | 109 | 15,598 | 14.3% | Field widget components |
| components/ | 87 | 14,633 | 13.4% | Reusable UI components |
| model/ | 29 | 8,537 | 7.8% | Relational model, sample server, record lifecycle |
| search/ | 30 | 7,152 | 6.6% | Search model, control panel, search bar, filters |
| webclient/ | 56 | 6,392 | 5.9% | Shell, actions, navbar, settings, user menu |
| services/ | 31 | 5,472 | 5.0% | ORM, hotkeys, UI, HTTP, commands, debug |
| ui/ | 20 | 2,566 | 2.4% | Dialogs, popover, tooltip, overlay |
| public/ | 11 | 1,868 | 1.7% | Public pages (colibri, interaction) |
| legacy/ | 6 | 1,976 | 1.8% | Legacy public widget bridge |
| boot/ | 2 | 80 | 0.1% | Bootstrap/startup |
| **Total** | **612** | **108,781** | **100%** | |

### Directory-Level Dependency Matrix

Read as "row imports from column". Numbers are import statement counts.

```
FROM \ TO     boot  comps  core   fields  model  search  servcs  sessn  ui    views  webclnt
boot            .      .     4       .      .       .       1      1     .       .       1
components      .      .   174       .      .       .       8      .    17       .       .
core            .      .     .       .      .       .       .      3     .       .       .
fields          .     47   292       .     19       .      12      .    11       .       .
legacy          .      1    11       .      .       .       .      .     .       .       .
model           .      .    49       .      .       .       9      .     .       .       .
public          .      1    15       .      .       .       .      .     .       .       .
search          .     28    71       .      1       .       6      1     1       .       .
services        .     11    96       .      .       .       .      3     2       .       .
ui              .      1    38       .      .       .       4      .     .       .       .
views           .     48   276      24     38      52      22      5    30       .       .
webclient       .     17   104       1      .       4      24      6     2      14       .
```

**Key observations for your analysis:**
- `core/` is the universal dependency (everything imports it) — it imports NOTHING except `session` (3 times)
- `views/` is the biggest consumer: imports from 8 other directories
- `fields/` imports `model/` (19 times) — this is a boundary concern (fields knowing about model internals)
- `webclient/` imports `views/` (14 times) — expected (webclient renders views)
- Three bidirectional dependencies exist (potential layering issues):
  - `services/ (11) <-> components/ (8)` — services import dropdown components for debug menus
  - `services/ (2) <-> ui/ (4)` — mutual dependency
  - `ui/ (1) <-> components/ (17)` — components use ui overlays; ui uses one component

### Actual Boundary Violations (Verified)

**IMPORTANT: Some violations claimed in previous analysis were WRONG.** The model layer does NOT directly import UI components (dialogs, notifications). Here is what ACTUALLY happens:

#### fields/ -> model/ (19 imports — coupling concern)
```
fields/parsers.js                         -> model/relational_model/operation
fields/specialized/user_groups/*          -> model/record
fields/specialized/domain/*               -> model/relational_model/record_hooks
fields/relational/reference/*             -> model/relational_model/record_hooks
fields/basic/boolean/*                    -> model/relational_model/record_hooks
fields/relational/x2many_dialog.js        -> model/relational_model/utils
fields/display/statusbar/*                -> model/relational_model/utils
fields/specialized/ace/*                  -> model/relational_model/record_hooks
fields/relational/many2many_tags/*        -> model/relational_model/utils
fields/relational/many2one/*              -> model/relational_model/utils
fields/relational/many2many_checkboxes/*  -> model/relational_model/utils
fields/relational/special_data.js         -> model/relational_model/record_hooks
fields/selection/radio/*                  -> model/relational_model/utils
fields/selection/selection_like_field.js   -> model/relational_model/utils
fields/relational/x2many/*               -> model/relational_model/utils
fields/basic/json_checkboxes/*            -> model/relational_model/record_hooks
fields/specialized/properties/*           -> model/relational_model/record_hooks
fields/field.js                           -> model/relational_model/utils
fields/media/image_url/*                  -> model/relational_model/record_hooks
```

Primary imports: `useRecordObserver` (8x), `getFieldDomain` (6x), `x2ManyCommands` (1x), `Operation` (1x), `extractFieldsFromArchInfo` (1x), `getFieldContext` (1x), `Record` (1x).

#### model/ -> services/ (9 imports — dependency direction concern)
```
model/sample_server.js                    -> services/orm_service (ORM class)
model/model.js                            -> services/user
model/relational_model/static_list.js     -> services/orm_service (x2ManyCommands)
model/relational_model/static_list_utils  -> services/orm_service (x2ManyCommands)
model/relational_model/command_builder.js -> services/orm_service (x2ManyCommands)
model/relational_model/field_values.js    -> services/orm_service (x2ManyCommands)
model/relational_model/dynamic_list.js    -> services/orm_service (x2ManyCommands)
model/relational_model/field_context.js   -> services/user
model/relational_model/record.js          -> services/orm_service (x2ManyCommands)
```

This is mainly `x2ManyCommands` (a simple enum/constant object) and `user` (current user singleton). The `ORM` class import in `sample_server.js` is the most concerning.

#### services/ -> components/ (11 imports — layer inversion)
```
services/install_scoped_app/*            -> components/dropdown/dropdown
services/tree_processor_service.js       -> components/tree_editor/* (7 imports!)
services/debug/debug_menu.js             -> components/dropdown/*
services/debug/debug_menu_basic.js       -> components/dropdown/*
```

The `tree_processor_service` importing 7 things from `tree_editor/` is a significant boundary violation — a service should not depend on component internals.

### Files Over 500 Lines (God Object Candidates)

| File | Lines | Directory |
|------|-------|-----------|
| list_renderer.js | 1,543 | views/list/ |
| search_model.js | 1,530 | search/ |
| record.js | 1,378 | model/relational_model/ |
| action_service.js | 1,251 | webclient/actions/ |
| static_list.js | 1,217 | model/relational_model/ |
| properties_field.js | 1,095 | fields/specialized/properties/ |
| pivot_model.js | 1,037 | views/pivot/ |
| calendar_model.js | 1,020 | views/calendar/ |
| graph_renderer.js | 974 | views/graph/ |
| public_widget.js | 969 | legacy/js/public/ |
| relational_model.js | 934 | model/relational_model/ |
| draggable_hook_builder.js | 868 | core/utils/dnd/ |
| control_panel.js | 805 | search/control_panel/ |
| kanban_renderer.js | 781 | views/kanban/ |
| search_bar.js | 779 | search/search_bar/ |
| form_compiler.js | 760 | views/form/ |
| custom_color_picker.js | 740 | components/color_picker/ |
| emoji_picker.js | 728 | components/emoji_picker/ |
| datetime_picker.js | 712 | components/datetime/ |
| sample_server.js | 708 | model/ |
| datetime_field.js | 701 | fields/temporal/datetime/ |
| form_controller.js | 690 | views/form/ |
| many2x_autocomplete.js | 630 | fields/relational/ |
| datetime_picker_service.js | 620 | components/datetime/ |
| field.js | 586 | fields/ |
| dynamic_list.js | 585 | model/relational_model/ |
| colibri.js | 577 | public/ |
| tree_processor_service.js | 576 | services/ |
| graph_model.js | 572 | views/graph/ |
| list_controller.js | 560 | views/list/ |
| clickbot.js | 557 | webclient/clickbot/ |
| py_date.js | 552 | core/py_js/ |
| list_keyboard_nav.js | 549 | views/list/ |
| autocomplete.js | 531 | components/autocomplete/ |
| view.js | 525 | views/ |
| export_data_dialog.js | 513 | views/view_dialogs/ |
| py_interpreter.js | 507 | core/py_js/ |
| debug_items.js | 501 | views/ |

### Reactive State Patterns (Inconsistency Map)

| Pattern | Usage (files) | Description |
|---------|---------------|-------------|
| `useState()` | 106 files | OWL hook — component-local reactive state |
| `reactive()` | 20 files | OWL utility — makes any object reactive |
| `extends Reactive` | 2 files | Class-based: `DataPoint` (model), `DropdownState` (components) |
| `markRaw()` | 11 files | Opt-out of reactivity for performance |

### Service Dependency Map (via `useService()`)

| Service | Usage Count | Role |
|---------|-------------|------|
| `orm` | 39 | Data access (RPC calls) |
| `notification` | 29 | Toast/notification display |
| `action` | 27 | Action execution/navigation |
| `dialog` | 26 | Modal dialog management |
| `ui` | 17 | UI state (block/unblock, active element) |
| `view` | 7 | View metadata loading |
| `field` | 7 | Field metadata resolution |
| `tree_processor` | 4 | Domain tree processing |
| `http` | 3 | Low-level HTTP |
| `hotkey` | 3 | Keyboard shortcuts |
| Others | 12 | title, menu, command, tooltip, popover, overlay, etc. |

### Addon Impact Data (What `addons_custom/` Imports)

These are the `@web/` import paths used by our ~100 custom addons. Changes to these paths have the HIGHEST migration cost:

| Import Path | Count | Risk if Moved |
|-------------|-------|--------------|
| `core/utils/hooks` | 19 | CRITICAL — most-used utility |
| `core/utils/patch` | 17 | CRITICAL — monkey-patching system |
| `core/registry` | 17 | CRITICAL — central registry |
| `core/l10n/translation` | 13 | HIGH — i18n |
| `fields/standard_field_props` | 4 | MEDIUM |
| `core/assets` | 4 | MEDIUM |
| `views/view_compiler` | 3 | MEDIUM |
| `search/layout` | 3 | LOW |
| `core/utils/concurrency` | 3 | LOW |
| `core/utils/dom/xml` | 3 | LOW |
| Others (1-2 each) | ~30 | LOW |

**Decision rule**: Any file imported 3+ times by addons_custom needs a re-export shim during migration. Files imported <3 times can be moved with a find-and-replace.

### Test File Sizes (Monster Files)

| Test File | Lines | Source File(s) Tested |
|-----------|-------|----------------------|
| list_view.test.js | 20,234 | list_renderer, list_controller, list_keyboard_nav |
| kanban_view.test.js | 15,456 | kanban_renderer, kanban_controller |
| one2many_field.test.js | 14,049 | x2many_field, static_list, record |
| form_view.test.js | 13,583 | form_controller, form_compiler |
| calendar_view.test.js | 6,231 | calendar_model, calendar_controller |
| many2one_field.test.js | 4,278 | many2one, many2x_autocomplete |
| pivot_view.test.js | 4,169 | pivot_model |
| mock_model.js (framework) | 4,098 | (test infrastructure) |
| search_panel_desktop.test.js | 3,501 | search_panel |
| properties_field.test.js | 3,227 | properties_field, property_definition |
| graph_view.test.js | 3,197 | graph_model, graph_renderer |
| interaction.test.js | 3,140 | interaction (public) |
| window_action.test.js | 2,906 | action_service |
| domain_selector.test.js | 2,753 | domain_selector, tree_editor |
| mock_server.js (legacy) | 2,587 | (test infrastructure) |
| settings_form_view.test.js | 2,490 | settings form |
| load_state.test.js | 2,459 | action_service (URL state) |
| many2many_field.test.js | 2,150 | many2many-related fields |
| router.test.js | 2,132 | router service |
| mock_server.test.js | 2,114 | mock server itself |
| many2many_tags_field.test.js | 2,107 | many2many_tags_field |
| search_bar.test.js | 2,056 | search_bar, search_model |

---

## THE PROMPT

You are a senior JavaScript architect performing a comprehensive structural analysis and refactoring plan for the Odoo 19.0 web module's JavaScript codebase.

**Use extended thinking deliberately.** You have the entire source code in context (~612 files, ~109K lines). Do not rush to output. Spend significant thinking time building your mental model, cross-referencing the pre-computed data against actual code, and validating your recommendations before writing them.

### Project Context

This is a **fork** of Odoo 19.0 where we own the codebase completely. There are no upstream compatibility constraints. We can rename files, move directories, split modules, change public APIs, and restructure freely. The goal is to transform this into a **best-in-class, state-of-the-art** frontend architecture.

The codebase uses:
- **OWL** (Odoo Web Library) — a reactive component framework similar to Vue/React
- **Service pattern** — dependency injection via `useService()` from a registry
- **Registry pattern** — named registries for components, views, fields, services, actions
- **No bundler** — Odoo uses its own asset bundling system (no webpack/vite/rollup)
- **No npm** — third-party libs are vendored in `static/lib/`
- **ES modules** — `@web/...` import paths resolved by Odoo's module loader

### Current State — Known Problems

These issues were identified from previous analysis. **The pre-computed data above updates and corrects some of these.** Use the data, not the descriptions below, as ground truth when they conflict.

#### 1. Boundary Violations

- **Fields import model internals**: 19 imports from `fields/` -> `model/`, primarily `useRecordObserver` (8x) and `getFieldDomain`/`getFieldContext` (7x). These should be injected or abstracted.
- **Model imports service constants**: 9 imports from `model/` -> `services/`, mainly `x2ManyCommands` (a constant) and `user` (a singleton). The constant should be co-located with model; the user dependency should be injected.
- **Services import component internals**: `tree_processor_service.js` imports 7 items from `components/tree_editor/` — a service depending on component internals is a layer inversion.
- **Search model has god-object tendencies**: `search_model.js` (1,530 lines) manages filters, group-by, favorites, comparison, and search panel state all in one class.

**NOTE**: Previous analysis claimed "model layer imports UI concerns (dialogs, notifications)" — this is **NOT TRUE** in the current codebase. Model imports `core/` and `services/` only. Verify this yourself against the actual imports.

#### 2. Tight Coupling

- **Action service is monolithic**: `action_service.js` (1,251 lines) handles action loading, execution, breadcrumbs, dialog actions, URL actions, client actions, and report actions.
- **Form controller is a god object**: `form_controller.js` (690 lines) mixes save/discard logic, button handling, status bar management, and layout.
- **List renderer is massive**: `list_renderer.js` (1,543 lines) handles column rendering, inline editing, grouping, optional columns, drag-and-drop, and keyboard navigation.
- **Record.js is the largest model file**: `record.js` (1,378 lines) manages values, changes, validation, save, discard, and field-level operations.

#### 3. File Organization Issues

- **Inconsistent granularity**: Some directories have one file doing everything (e.g., `search_model.js`), while others are well-decomposed (e.g., `tree_editor/` with 19 files).
- **Flat dumps**: `core/utils/` is a grab-bag of unrelated utilities (collections, DOM, DnD, format) — some should be promoted to proper modules.
- **Missing abstraction layers**: No clear "data access layer" separating RPC mechanics from business logic.
- **Components directory is too flat**: 87 files in `components/` spanning simple UI primitives (checkbox, copy_button) and complex features (domain_selector, tree_editor, emoji_picker).

#### 4. State Management Inconsistencies

- Four different reactive patterns: `useState` (106 files), `reactive()` (20 files), `extends Reactive` (2 files), `markRaw` (11 files).
- Record state has a complex three-layer model (`_values`, `_changes`, `data`) that is hard to reason about.
- No clear state machine for complex flows (form save, action transitions).

#### 5. Missing Modern Patterns

- No TypeScript (only `@types/` stubs).
- No formal module boundary enforcement.
- No dependency graph visualization or validation.
- Limited use of modern JS patterns (WeakRef, FinalizationRegistry, AbortController for cleanup).
- No structured error types — errors are mostly strings or generic Error instances.

### What "Best in Class" Looks Like

The target architecture should embody these principles:

#### A. Feature-Sliced Design (FSD) — Layered Architecture
```
shared/          -> Pure utilities, no Odoo knowledge (colors, collections, DOM, format)
entities/        -> Core data types (Record, Field, Domain, Action) — no UI
features/        -> Self-contained features (search, field widgets, view types)
widgets/         -> Composed UI blocks (control panel, navbar, menus)
pages/           -> Full page compositions (webclient, settings, public)
```

Each layer can only import from layers below it. Never upward.

#### B. Explicit Module Boundaries
- Every directory with 3+ files gets an `index.js` that defines the public API.
- Internal files are prefixed with `_` or placed in an `internal/` subdirectory.
- Cross-feature imports go through the public API only.

#### C. Single Responsibility
- No file over 500 lines (split into focused modules).
- No class with more than one reason to change.
- Extract strategies, policies, and algorithms into separate files.

#### D. Dependency Inversion
- The model layer NEVER imports UI. It declares hooks/callbacks that controllers wire.
- Views don't import from other views. Shared logic lives in `shared/` or view-level utilities.
- Fields don't import view internals. They use the field registry and injected props.

#### E. Typed Interfaces
- JSDoc `@typedef` for all cross-module data structures.
- `@param` and `@returns` on all public functions.
- Eventually: TypeScript migration path.

#### F. Testability
- Pure functions extracted from stateful classes.
- Dependency injection over global registry lookups where possible.
- Each module testable in isolation.

---

### Your Task

Analyze the ENTIRE JavaScript codebase loaded in context and produce the deliverables below.

**Thinking checkpoints** — At these points in your thinking, pause and validate:

1. After building the dependency graph: "Does my graph match the pre-computed matrix? If not, what did I miss?"
2. After identifying god objects: "For each proposed split, can module A be tested without module B?"
3. After proposing directory moves: "How many import path updates does this cause? Is the cost justified?"
4. After proposing abstractions: "Does this abstraction solve a real problem I can point to in 3+ files, or is it speculative generality?"

---

#### Deliverable 1: Dependency Graph Analysis

For each top-level directory, provide:

```
### [directory_name]/
- Layer: [shared | entity | feature | widget | page | infrastructure]
- Lines: [N] | Files: [N]
- Inbound: [list of directories that import from this one, with counts]
- Outbound: [list of directories this one imports from, with counts]
- Violations: [specific imports that violate the target layering, with file:line]
- Coupling: [High | Medium | Low] — [1-sentence justification]
```

Then present:
1. **Proposed layer assignment** for each directory (mapping current -> target FSD layer)
2. **Violation resolution plan** for each violation (inject, extract, move, or accept)
3. **ASCII dependency diagram** showing current vs target state

#### Deliverable 2: God Object Decomposition Plan

For EVERY file over 500 lines (38 files listed above), provide:

```
### [filename] ([N] lines, [directory])

**Responsibilities** (identify 2-5 distinct concerns):
1. [Concern A] — lines [N-M], methods: [list]
2. [Concern B] — lines [N-M], methods: [list]

**Proposed Split**:
| New File | Lines (est.) | Key Exports | Depends On |
|----------|-------------|-------------|------------|
| [name].js | ~[N] | [exports] | [imports] |

**Shared State**: [What state must be passed between the new modules?]
**Public API Impact**: [Does this break any external API? Migration path?]
**Risk**: [Low | Medium | High] — [why]
```

**Decision framework for splitting:**
- SPLIT if: distinct concerns, >2 state groups, testable independently, different change frequencies
- KEEP TOGETHER if: deeply interleaved state, split would create excessive parameter passing, <600 lines with high cohesion
- For each "keep together" decision, explain WHY the file is cohesive despite its size

#### Deliverable 3: Directory Restructure Proposal

For every file that moves, use this format:

```
OLD: [current path relative to static/src/]
NEW: [proposed path relative to static/src/]
REASON: [1 sentence]
ADDON_IMPACT: [number of addons_custom imports affected, or "none"]
IMPORT_UPDATES: [estimated number of files that need import path changes]
```

Group by subsystem. After each group, provide a migration script concept (find-and-replace patterns).

**Priority order for moves:**
1. Zero-addon-impact moves (pure internal restructuring)
2. Low-addon-impact moves (<3 imports affected, shim sufficient)
3. High-addon-impact moves (>3 imports affected, requires coordinated update)

#### Deliverable 4: Abstraction Layer Proposals

For each proposed abstraction:

```
### [Abstraction Name]

**Problem**: [Concrete examples of the problem in 3+ files, with file:line references]
**Interface**:
```js
// JSDoc or TypeScript-style interface definition
```
**Replaces**: [Which existing code this replaces]
**Migration**: [Step-by-step migration path]
**Justification**: [Why this isn't speculative generality — concrete benefit measurement]
```

Propose abstractions for:
1. **Data Access Layer**: Abstraction over RPC that models can use without knowing about HTTP/JSON-RPC.
2. **State Machines**: For complex stateful flows (form save, action transitions, search model).
3. **Event System**: Typed events replacing string-based bus events.
4. **Error Types**: Structured error hierarchy replacing string errors.
5. **Plugin System**: For extensibility points (field widgets, view types, actions).
6. **Record Observer Pattern**: Replace the 19 direct `fields/ -> model/` imports with an event/observer abstraction.

**Critical filter**: Only propose abstractions that solve problems visible in 3+ files. If you can't point to 3 concrete examples, it's speculative generality — log it in `rejected.md` with the reason "speculative generality: fewer than 3 concrete use cases found" and move on.

**Seed rejected.md**: During Phase 1 analysis, you WILL encounter approaches that seem promising but don't hold up under scrutiny. Log EVERY one of these in a `rejected.md` section of your output. This is valuable — it prevents future sessions from re-exploring dead ends. Aim for at least 5-10 rejected approaches in Phase 1 output.

#### Deliverable 5: Phased Execution Plan

Organize all proposed changes into phases. For each phase:

```
### Phase [N]: [Name] — [Risk Level]

**Goal**: [1 sentence]
**Prerequisites**: [Which phases must complete first]
**Duration estimate**: [S/M/L based on number of files touched]

**Changes**:
| # | Change | Files Touched | Import Updates | Risk |
|---|--------|--------------|---------------|------|
| 1 | [specific change] | [N] | [N] | [L/M/H] |

**Verification**:
- [ ] [Specific test suite that must pass]
- [ ] [Manual check if applicable]
- [ ] [Behavioral invariant to verify]

**Rollback**: [How to undo this phase if it causes problems]
```

Phases (refine or reorder based on your analysis):

1. **Foundation** — Extract pure utilities, add `index.js` public APIs, add JSDoc types (no behavior change)
2. **Constants & Types** — Move `x2ManyCommands` to model/, extract shared types/interfaces
3. **Decouple Model Layer** — Remove service imports from model/, formalize dependency injection
4. **Decouple Fields from Model** — Replace direct model imports with injected abstractions
5. **Fix Service/Component Inversion** — Extract tree_processor logic from component internals
6. **Decompose God Objects** — Split large files (one per PR), maintain backward-compatible re-exports
7. **Restructure Directories** — Move files to new FSD locations, update import paths
8. **New Abstractions** — State machines, typed errors, plugin system formalization

#### Deliverable 6: Test Architecture Overhaul

**6a. Test Granularity & Tagging Strategy**

Propose a tagging scheme where developers can run:
```bash
# Only tests affected by changes to model/
--test-tags=@model

# Only list view tests
--test-tags=@view-list

# Smoke tests (~30 seconds)
--test-tags=@smoke

# Full regression
--test-tags=@regression
```

Define the tag taxonomy and which files get which tags.

**6b. Monster Test File Decomposition**

For each test file over 2,000 lines (22 files):

| Test File | Lines | Proposed Split | Grouping Criterion | Est. Tests per Split |
|-----------|-------|---------------|-------------------|---------------------|
| list_view.test.js | 20,234 | [list splits] | By feature | [counts] |

**6c. Mock Server Unification**

Analyze the two mock systems:
- `_framework/mock_server/` (modern, `mock_model.js` at 4,098 lines)
- `legacy/helpers/mock_server.js` (2,587 lines)

Propose:
- Which one survives
- Migration path for the other
- How to reduce `mock_model.js` from 4,098 lines

**6d. Test Performance Optimization**

Identify:
- Top 5 slow test patterns (with examples)
- Proposed shared fixtures / setup factories
- Tests that could be converted from integration to unit tests
- Watch mode / affected-tests-only strategy

**6e. Test-Source Colocation**

Evaluate colocated tests (`views/list/list_renderer.test.js` next to source) vs current mirror structure (`static/tests/views/list/`). Pros/cons table and recommendation.

#### Deliverable 7: Anti-Patterns Catalog

For each anti-pattern found:

```
### [Pattern Name] — [Priority: Critical | High | Medium | Low]
**Where**: [file(s) with line references]
**Problem**: [1-2 sentences]
**Fix**: [Specific proposed fix]
**Effort**: [S/M/L]
```

Look for (but don't limit to):
- God objects/classes (>500 lines, >3 responsibilities)
- Feature envy (class using another class's data more than its own)
- Shotgun surgery (one conceptual change requires editing 5+ files)
- Inappropriate intimacy (classes that know too much about each other's internals)
- Speculative generality (abstractions without concrete justification)
- Dead code (exported but never imported)
- Copy-paste duplication (near-identical logic in 2+ files)
- Primitive obsession (passing raw strings/numbers where a typed object would prevent errors)
- Inconsistent patterns (same problem solved different ways in different files)

---

### Constraints

1. **OWL framework is fixed** — We cannot replace OWL. Work within its component model, reactivity system, and lifecycle.
2. **Registry pattern stays** — The service/component/field registry is the extension mechanism. Improve it, don't replace it.
3. **No bundler** — Odoo's asset system concatenates files. Import paths use `@web/...` resolved at build time. No tree-shaking, no code splitting beyond asset bundles.
4. **Backward compatibility for addons** — ~100 custom addons in `addons_custom/` import from `@web/...`. The addon impact data above lists the critical paths. Provide re-export shims for any moved path that addons use.
5. **Incremental execution** — The app must work after every individual change. No "big bang" refactors.
6. **Test coverage** — Every structural change must pass existing tests. New abstractions need new tests.

### Output Format

Structure your response as a single comprehensive document with clear headers for each deliverable. Use the templates above for consistency. Use code blocks for interface definitions. Use ASCII diagrams for dependency graphs.

**Be exhaustive and specific.** Reference actual file names, line numbers, function names, and import paths from the codebase in context. Do not make assumptions — base every recommendation on code you can see.

**Distinguish certainty levels:**
- "VERIFIED: [claim]" — you checked the code and confirmed
- "LIKELY: [claim]" — consistent with patterns you see but not fully traced
- "UNCERTAIN: [claim]" — needs further investigation in a follow-up session

**Total expected output: 20,000-30,000 words.** Use your full output budget. This is a once-per-project analysis — thoroughness matters more than brevity.

---

## Session Continuity Protocol

The biggest risk in multi-session refactoring is **losing context between phases**. This section defines exactly how sessions hand off to each other so no re-investigation happens.

### The Checkpoint File System

Each session produces a checkpoint file saved to `core/addons/web/refactor/`. These files are the **single source of truth** — they're loaded at the start of the next session instead of re-deriving everything.

```
core/addons/web/refactor/
├── REFACTOR_STATE.md          # Master progress tracker (updated every session)
├── phase1_analysis.md         # Phase 1 output: dependency graph, god objects, plan
├── phase2_output.md           # Phase 2 output: what was done, what was discovered
├── phase3_output.md           # etc.
├── decisions.md               # Decision log: WHY choices were made (ADRs)
├── rejected.md                # REJECTED ideas with full rationale (prevents re-exploration)
└── blockers.md                # Discoveries that changed the plan
```

### REFACTOR_STATE.md Format

This file is created at the end of Phase 1 and updated at the end of every subsequent session:

```markdown
# Refactoring State — Last Updated: [date]

## Current Phase: [N] — [Name]
## Next Action: [Exact first thing the next session should do]

## Completed
- [x] Phase 1: Analysis & Plan (session date)
  - Output: phase1_analysis.md
  - Key decisions: [1-line summaries]
- [x] Phase 2: Constants & Types (session date)
  - Files changed: [list]
  - Tests verified: [which suites passed]

## In Progress
- [ ] Phase 3: Decouple Model Layer
  - Started: [date]
  - Done: model/relational_model/command_builder.js (moved x2ManyCommands)
  - Remaining: [specific files/tasks]
  - Blocked: [if anything]

## Not Started
- [ ] Phase 4: Decouple Fields from Model
- [ ] Phase 5: Fix Service/Component Inversion
- [ ] Phase 6: Decompose God Objects
- [ ] Phase 7: Restructure Directories
- [ ] Phase 8: New Abstractions

## Plan Deviations
- [Date]: Original plan said X, but we discovered Y. Changed approach to Z.
  - Affected phases: [list]
  - See: decisions.md#[anchor]
```

### decisions.md Format (Architecture Decision Records)

Every non-obvious decision gets logged — both approvals AND rejections:

```markdown
## ADR-001: [Decision Title] — [APPROVED | REJECTED | DEFERRED]

**Date**: [YYYY-MM-DD]
**Phase**: [N]
**Context**: [What we were trying to do]
**Options Considered**:
1. [Option A] — [pros/cons]
2. [Option B] — [pros/cons]
3. [Option C] — [pros/cons]
**Decision**: [Which option and WHY]
**Rejected alternatives**: [Which options were rejected and the SPECIFIC reason]
**Consequences**: [What this means for later phases]
**Revisit if**: [Under what conditions this decision should be reconsidered]
```

### rejected.md Format (No-Go Registry)

**CRITICAL: This file prevents future sessions from re-proposing already-explored ideas.**

Every rejected approach, failed experiment, or abandoned direction gets logged here. Future sessions MUST check this file before proposing any structural change.

```markdown
# Rejected Approaches

## REJ-001: [Rejected Idea Title]
**Date**: [YYYY-MM-DD]
**Proposed by**: [Phase N analysis / Session N]
**What was proposed**: [Clear description of the rejected approach]
**Why it was rejected**: [Specific, technical reason — not just "didn't work"]
**Evidence**: [File references, test failures, coupling discovered, etc.]
**What to do instead**: [The approved alternative, or "no action needed"]
**Keywords**: [searchable tags: e.g., "state-machine", "model-split", "typescript"]

## REJ-002: Replace OWL reactivity with signals
**Date**: 2025-03-05
**Proposed by**: Phase 1 analysis
**What was proposed**: Replace the 4 reactive patterns with a unified signals system
**Why it was rejected**: OWL framework is fixed (Constraint #1). The 4 patterns (useState, reactive, Reactive class, markRaw) are all OWL primitives — we can standardize WHICH to use but can't replace the underlying mechanism.
**What to do instead**: Establish a convention (useState for components, reactive() for services, Reactive class only for DataPoint) and document in CONVENTIONS.md.
**Keywords**: reactivity, signals, state-management, owl
```

**Rules for rejected.md:**
1. Every session that considers and rejects an approach MUST add it here
2. Every session that proposes a new approach MUST search rejected.md first (by keywords)
3. A rejection can be reversed ONLY if the conditions in "Revisit if" (from the ADR) are met
4. Include enough detail that someone reading ONLY rejected.md understands why it was rejected without needing to re-read source code

### Phase 1 Structured Output Requirements

Phase 1 output (`phase1_analysis.md`) MUST include these machine-parseable sections in addition to prose analysis:

#### Section A: File Move Registry (YAML-like)

```
## File Moves

### Move Group: Pure Utilities to shared/
PHASE: 7
RISK: Low
ADDON_IMPACT: 0

- OLD: core/utils/collections/array.js
  NEW: shared/collections/array.js
  UPDATES: 45

- OLD: core/utils/format/colors.js
  NEW: shared/format/colors.js
  UPDATES: 12

### Move Group: x2ManyCommands to model/
PHASE: 2
RISK: Low
ADDON_IMPACT: 2

- OLD: services/orm_service.js (export x2ManyCommands)
  NEW: model/relational_model/commands.js
  UPDATES: 7
```

#### Section B: Split Registry

```
## File Splits

### Split: search_model.js (1530 lines)
PHASE: 6
RISK: Medium

- NEW: search/search_model.js (~400 lines) — core orchestrator
  EXPORTS: SearchModel
  METHODS: constructor, setup, notify, _getGroupBysFromContext

- NEW: search/filter_manager.js (~350 lines)
  EXPORTS: FilterManager
  METHODS: createNewFilters, deactivateGroup, toggleFilter, ...
  SHARED_STATE: searchItems (passed via constructor)

- NEW: search/group_by_manager.js (~200 lines)
  EXPORTS: GroupByManager
  METHODS: createNewGroupBy, toggleGroupBy, ...
  SHARED_STATE: searchItems, query (passed via constructor)

[etc.]
```

#### Section C: Phase-Specific File Lists

For each execution phase, list EXACTLY which files to load in that session:

```
## Phase 2 Session — Load List (~15K tokens)

### Source files to load:
core/addons/web/static/src/services/orm_service.js
core/addons/web/static/src/model/relational_model/static_list.js
core/addons/web/static/src/model/relational_model/static_list_utils.js
core/addons/web/static/src/model/relational_model/command_builder.js
core/addons/web/static/src/model/relational_model/field_values.js
core/addons/web/static/src/model/relational_model/dynamic_list.js
core/addons/web/static/src/model/relational_model/record.js
core/addons/web/static/src/model/relational_model/field_context.js
core/addons/web/static/src/model/model.js
core/addons/web/static/src/model/sample_server.js
core/addons/web/static/src/services/user.js

### Context files to load (read-only, for understanding):
core/addons/web/refactor/REFACTOR_STATE.md
core/addons/web/refactor/phase1_analysis.md
core/addons/web/refactor/decisions.md

### Tests to run after changes:
--test-tags=@model
```

### Phase 2+ Session Prompt Template

Each execution session starts with this prompt (adapt per phase):

```
You are continuing a multi-session refactoring of the Odoo web module JS codebase.

**Read these files first (in order):**
1. REFACTOR_STATE.md — current progress and next action
2. rejected.md — MANDATORY: check before proposing ANY new approach
3. decisions.md — past decisions (check for relevant context)
4. phase[N-1]_output.md — what the last session did
5. phase1_analysis.md — Section [X] for this phase's plan

**Your task for this session:**
[Specific task from REFACTOR_STATE.md "Next Action"]

**Rules:**
1. Follow the plan from phase1_analysis.md unless you discover something that makes it wrong.
2. Before proposing any structural change, search rejected.md for related keywords. If a similar idea was already rejected, either follow the approved alternative or explain why conditions have changed.
3. If you discover something that changes the plan, STOP and document it in blockers.md before continuing.
4. At the end of this session, update REFACTOR_STATE.md with exactly what you did and what comes next.
5. Write phase[N]_output.md with: files changed, decisions made, problems found, verification results.
6. Log ALL decisions (including rejections) in decisions.md. Log all rejected approaches in rejected.md.
7. If you can't finish the phase in one session, record exactly where you stopped.

**Verification checklist for this phase:**
- [ ] All changed files pass linting
- [ ] [Specific test suite] passes
- [ ] No new boundary violations introduced (check: grep -r "from.*@web/[target]" [source_dir])
- [ ] REFACTOR_STATE.md updated
- [ ] phase[N]_output.md written
- [ ] Any new decisions logged in decisions.md
- [ ] Any rejected approaches logged in rejected.md
```

### Session Handoff Checklist

Before ending ANY session, verify you've produced:

1. **Updated `REFACTOR_STATE.md`** with:
   - Current phase status
   - Exact next action (specific enough that the next session can start immediately)
   - Any blockers or plan deviations
2. **`phase[N]_output.md`** with:
   - Files created/modified/deleted (with diffs or summaries)
   - Decisions made and rationale
   - Unexpected discoveries
   - Test results
3. **Updated `decisions.md`** for every non-obvious choice (ADR format, numbered sequentially)
4. **Updated `rejected.md`** for EVERY approach that was considered and rejected — even small ones. This is the most important file for preventing re-exploration in future sessions.
5. **Updated `blockers.md`** if anything changes the plan

---

## For Phase 2+ Execution Sessions

When starting an execution session, load:

1. **Always**: `REFACTOR_STATE.md` (progress and next action)
2. **Always**: `rejected.md` (MUST read before proposing anything — prevents re-exploration)
3. **Always**: `decisions.md` (past ADRs for context)
4. **Always**: `blockers.md` (known obstacles)
5. **Always**: The relevant section of `phase1_analysis.md` (the plan for this phase)
6. **Always**: The previous phase's `phase[N-1]_output.md`
7. **Phase-specific**: Only the source files listed in the Phase-Specific File List (from Phase 1 output)

This keeps each session well within token budget while maintaining full context for the subsystem being refactored. No re-investigation needed — everything is in the checkpoint files.

---

## Appendix A: File Loading Script

Use this script to concatenate all source files into a single loadable document:

```bash
#!/bin/bash
# Generate a single file with all JS source for context loading
# Output: web_js_source.txt (~4MB, ~1.07M tokens)

OUTPUT="web_js_source.txt"
SRC="core/addons/web/static/src"

echo "# Odoo Web Module - Complete JS Source" > "$OUTPUT"
echo "# Generated: $(date -I)" >> "$OUTPUT"
echo "# Files: $(find "$SRC" -name '*.js' ! -name 'emoji_data.js' | wc -l)" >> "$OUTPUT"
echo "" >> "$OUTPUT"

# Machine docs first
for doc in core/addons/web/machine_doc_v1/*.md core/addons/web/doc/*.md; do
    echo "========== FILE: $doc ==========" >> "$OUTPUT"
    cat "$doc" >> "$OUTPUT"
    echo "" >> "$OUTPUT"
done

# Manifest
echo "========== FILE: core/addons/web/__manifest__.py ==========" >> "$OUTPUT"
cat core/addons/web/__manifest__.py >> "$OUTPUT"
echo "" >> "$OUTPUT"

# All JS source files (sorted for deterministic order)
find "$SRC" -name "*.js" ! -name "emoji_data.js" | sort | while read -r file; do
    echo "========== FILE: $file ==========" >> "$OUTPUT"
    cat "$file" >> "$OUTPUT"
    echo "" >> "$OUTPUT"
done

echo "Generated $OUTPUT ($(wc -c < "$OUTPUT") bytes, ~$(( $(wc -c < "$OUTPUT") / 4 )) tokens est.)"
```

## Appendix B: Test Loading Scripts

The test file (~7.7MB, ~2.2M tokens) won't fit in a single 1M session. Split by directory:

```bash
#!/bin/bash
# Generate test files for dedicated test analysis sessions
TESTS="core/addons/web/static/tests"

# Session 3a: views/ tests (~107 files, ~1M tokens)
OUTPUT="web_tests_views.txt"
find "$TESTS/views" -name "*.js" | sort | while read -r file; do
    echo "========== FILE: $file ==========" >> "$OUTPUT"
    cat "$file" >> "$OUTPUT"
    echo "" >> "$OUTPUT"
done

# Session 3b: core/ + components/ tests (~99 files)
OUTPUT="web_tests_core_components.txt"
find "$TESTS/core" "$TESTS/components" -name "*.js" | sort | while read -r file; do
    echo "========== FILE: $file ==========" >> "$OUTPUT"
    cat "$file" >> "$OUTPUT"
    echo "" >> "$OUTPUT"
done

# Session 3c: webclient/ + search/ + services/ tests (~64 files)
OUTPUT="web_tests_webclient_search_services.txt"
find "$TESTS/webclient" "$TESTS/search" "$TESTS/services" -name "*.js" | sort | while read -r file; do
    echo "========== FILE: $file ==========" >> "$OUTPUT"
    cat "$file" >> "$OUTPUT"
    echo "" >> "$OUTPUT"
done
```
