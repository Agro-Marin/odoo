# Rejected Approaches

## REJ-001: New Plugin System Abstraction
**Date**: 2026-03-05
**Proposed by**: Phase 1 analysis (Deliverable 4 prompt)
**What was proposed**: Create a formal PluginSystem abstraction for fields, views, and actions with lifecycle hooks, dependency declaration, and activation/deactivation.
**Why it was rejected**: The registry pattern IS the plugin system. `fieldRegistry.add()`, `viewRegistry.add()`, `actionRegistry.add()` already provide registration, discovery, validation (via `addValidation`), and extension. No evidence of 3+ files needing anything the registry doesn't already serve.
**Evidence**: `registry.js` already has EventBus-based notification (`ADD`/`REMOVE` events), validation schemas, sub-categories, and `useRegistry()` hook for reactive subscription.
**What to do instead**: Continue using the registry pattern. Document common patterns in CONVENTIONS.md if needed.
**Keywords**: plugin, extensibility, registry, field-widget, view-type

## REJ-002: Replace OWL Reactivity with Signals
**Date**: 2026-03-05
**Proposed by**: Phase 1 analysis
**What was proposed**: Replace the 4 reactive patterns (useState, reactive, Reactive class, markRaw) with a unified signals system.
**Why it was rejected**: OWL framework is fixed (Constraint #1). The 4 patterns are all OWL primitives. We can standardize WHICH to use per context but can't replace the underlying mechanism.
**Evidence**: `STATE_MANAGEMENT.md` already documents the decision tree: useState for components, reactive() for services, Reactive class only for DataPoint. markRaw is a performance optimization, not a pattern choice.
**What to do instead**: Enforce the existing convention via code review. No code change needed.
**Keywords**: reactivity, signals, state-management, owl, useState, reactive

## REJ-003: Colocate Tests with Source Files
**Date**: 2026-03-05
**Proposed by**: Phase 1 analysis (Deliverable 6e)
**What was proposed**: Move test files next to their source (e.g., `views/list/list_renderer.test.js`).
**Why it was rejected**: Odoo's asset bundling system includes files by glob pattern (e.g., `"web/static/src/views/**/*"`). Colocating tests would include them in production bundles unless exclusion rules are added to every bundle definition.
**Evidence**: `__manifest__.py` uses `"web/static/src/model/**/*"`, `"web/static/src/views/**/*"`, etc. Adding `("remove", "web/static/src/**/*.test.js")` to every bundle is error-prone and fragile.
**What to do instead**: Keep mirror structure in `static/tests/`. Improve discoverability via test tagging.
**Keywords**: test-colocation, test-structure, asset-bundles, manifest

## REJ-004: Split list_renderer.js into Multiple Components
**Date**: 2026-03-05
**Proposed by**: Phase 1 analysis (Deliverable 2)
**What was proposed**: Split the 1,543-line ListRenderer into separate sub-components (ListCell, ListGroup, ListHeader, etc.).
**Why it was rejected**: ListRenderer has already been extensively decomposed through 9 OWL hooks (`useListKeyboardNavigation`, `useListSelection`, `useListOptionalFields`, `useListVirtualization`, `useListAggregates`, `useMagicColumnWidths`, `ListGridState`, `list_group_layout`, `list_column_utils`). The remaining lines are the OWL component wiring and rendering getters, which must live in a single Component due to OWL's single-`setup()` contract.
**Evidence**: Most methods in ListRenderer are 3-10 line getters or thin delegation wrappers. The actual logic lives in the extracted hooks. Only ~350 lines of pure rendering helpers could be extracted, which was proposed as `list_cell_helpers.js`.
**What to do instead**: Extract `list_cell_helpers.js` (~350 lines of pure functions) but keep the Component class intact.
**Keywords**: list-renderer, component-split, owl-hooks, god-object

## REJ-005: Explicit State Machine for Record Save
**Date**: 2026-03-05
**Proposed by**: Phase 1 analysis (Deliverable 4)
**What was proposed**: Introduce an XState-like state machine for the form save lifecycle (CLEAN→DIRTY→VALIDATING→SAVING→RELOADING→CLEAN).
**Why it was rejected**: The implicit mutex-serialized flow in `record.js` works correctly and is well-tested. The mutex guarantees serial execution — `save()` cannot be called during `save()`. Adding a state machine would be a significant refactor with risk of introducing subtle timing bugs, for a flow that has no known issues.
**Evidence**: `record.js` uses `model.mutex.exec()` for all state transitions. The `_save` method (166 lines) handles validity, RPC, and reload in a single serialized call. No bugs related to state confusion have been reported.
**What to do instead**: Defer to Phase 8. If a concrete bug arises from state confusion, revisit then.
**Keywords**: state-machine, form-save, record, mutex, xstate

## REJ-006: Unified Error Hierarchy (Phase 1)
**Date**: 2026-03-05
**Proposed by**: Phase 1 analysis (Deliverable 4)
**What was proposed**: Create a unified error class hierarchy from the 28 existing error classes.
**Why it was rejected**: The 28 error classes work correctly today. They are caught and handled at specific points in the codebase. Unifying them would require:
1. Creating a base class hierarchy (OdooError → RPCError, UIError, etc.)
2. Updating all 28 classes
3. Updating all catch blocks
The effort is not justified by a concrete problem.
**Evidence**: Error classes are domain-specific (`RPCError`, `InvalidDomainError`, `CalendarParseArchError`) and caught by code that knows the specific type. A base class would add no value to existing catch blocks.
**What to do instead**: Document all 28 error classes in `error_catalog.md` (Phase 1). Defer hierarchy to Phase 8 if error handling becomes more centralized.
**Keywords**: error-hierarchy, error-types, exception-handling, structured-errors

## REJ-007: Move `user` Singleton to Shared Module
**Date**: 2026-03-05
**Proposed by**: Phase 1 analysis
**What was proposed**: Move `services/user.js` to `core/` or `shared/` since it's used as a singleton, not as a registered service.
**Why it was rejected**: While `user` is exported as a module-level singleton (not via the service registry), it depends on `session`, `cookie`, and `rpc` — all of which are service-layer or infrastructure concepts. Moving it to core/ would pull those dependencies into the shared layer.
**Evidence**: `services/user.js` imports from `@web/core/browser/cookie`, `@web/core/network/rpc`, `@web/session` — these are runtime dependencies that don't belong in the pure utility layer.
**What to do instead**: Keep `user` in services/ but inject it into model/ via constructor (Phase 3) instead of direct import.
**Keywords**: user-singleton, dependency-injection, services-layer

## REJ-008: TypeScript Migration (Phase 1-6)
**Date**: 2026-03-05
**Proposed by**: General architecture improvement
**What was proposed**: Begin TypeScript migration during the refactoring phases.
**Why it was rejected**: Odoo has no bundler — its asset system concatenates raw JS files. TypeScript would require a build step that doesn't exist in the pipeline. The JSDoc type annotations (81% coverage) provide type checking without a build step when used with `@ts-check` (which is already enabled in many files).
**Evidence**: The first line of most files is `// @ts-check`. TypeScript's type inference engine reads JSDoc annotations natively. Adding `.ts` files would require modifying the asset bundler.
**What to do instead**: Continue improving JSDoc annotations. Add `@typedef` for cross-module data structures. Use `@ts-check` in all files.
**Keywords**: typescript, type-system, jsdoc, build-pipeline, asset-bundler

## REJ-009: Split pivot_model.js
**Date**: 2026-03-05
**Proposed by**: Phase 1 analysis (Deliverable 2)
**What was proposed**: Split the 1,037-line PivotModel into separate modules for header management, cell computation, and RPC loading.
**Why it was rejected**: PivotModel has deeply interleaved state: `rowGroupTree`, `colGroupTree`, `cells`, `headers`, `measures`, and `sortedColumn` all reference each other. Every method reads from and potentially mutates multiple state groups. Splitting would create excessive parameter passing — each extracted module would need access to 5+ shared state variables.
**Evidence**: `_prepareData` reads from `rowGroupTree`, `colGroupTree`, and `measures` to build `cells`. `_sortRows`/`_sortColumns` reads from `cells`, `headers`, and `sortedColumn`. `_loadData` writes to all state groups.
**What to do instead**: Keep as single file. The model manages a single concern (pivot table state) cohesively.
**Keywords**: pivot-model, god-object, interleaved-state, data-model

## REJ-010: Split calendar_model.js
**Date**: 2026-03-05
**Proposed by**: Phase 1 analysis (Deliverable 2)
**What was proposed**: Split the 1,020-line CalendarModel into date navigation, event CRUD, and filter management.
**Why it was rejected**: Similar to PivotModel — the calendar model's state (date range, events, filters, quick-create) is deeply interconnected. Date navigation affects which events are loaded; filters affect which events are displayed; quick-create needs the current date range. High cohesion, single domain concern.
**What to do instead**: Keep as single file.
**Keywords**: calendar-model, god-object, date-state, view-model
