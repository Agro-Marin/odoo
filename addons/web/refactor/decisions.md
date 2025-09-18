# Architecture Decision Records

## ADR-001: Registry IS the Plugin System — REJECTED (the proposal, not the registry)

**Date**: 2026-03-05
**Phase**: 1
**Context**: The refactor prompt asks for a "Plugin System" abstraction proposal for extensibility points (field widgets, view types, actions).
**Options Considered**:
1. Create a new PluginSystem abstraction — formal plugin lifecycle, dependency declaration, activation hooks
2. Keep the existing registry pattern as-is
3. Enhance the registry with lifecycle hooks

**Decision**: REJECTED Option 1 (new abstraction). The registry pattern already provides registration, discovery, validation, and extension. Adding a "plugin system" on top of it would be speculative generality — there are zero concrete use cases that the registry doesn't already serve.

**Rejected alternatives**: Option 1 rejected because `fieldRegistry.add()`, `viewRegistry.add()`, `actionRegistry.add()` already serve all current extension patterns. No evidence of 3+ files needing anything beyond this.
**Consequences**: None — the registry continues to work.
**Revisit if**: A concrete need for plugin lifecycle (activation/deactivation, dependency ordering, conditional loading) emerges in 3+ concrete use cases.

## ADR-002: Keep Mirror Test Structure (not colocated) — APPROVED

**Date**: 2026-03-05
**Phase**: 1
**Context**: Evaluated colocating tests next to source vs keeping the current `static/tests/` mirror structure.
**Options Considered**:
1. Colocate tests next to source files
2. Keep mirror structure (current)

**Decision**: APPROVED Option 2 (keep mirror structure).
**Rejected alternatives**: Colocation rejected because Odoo's asset bundling system includes files by glob pattern. Colocating tests would require adding exclusion rules (`("remove", "web/static/src/**/*.test.js")`) to every asset bundle definition. The migration cost outweighs the discoverability benefit.
**Consequences**: Tests remain in `static/tests/`, mirroring `static/src/`.
**Revisit if**: Odoo's asset system gains native test file exclusion or a bundler is adopted.

## ADR-003: FSD Layer Assignment — APPROVED

**Date**: 2026-03-05
**Phase**: 1
**Context**: Assigning each current directory to a Feature-Sliced Design layer.
**Options Considered**:
1. core/services/ui → shared; model → entities; fields/components/search/views → features; webclient/public → pages
2. Alternative: model + fields → entities (grouping data types with their UI)
3. Alternative: services as its own "infrastructure" layer

**Decision**: APPROVED Option 1.
**Rejected alternatives**: Option 2 rejected — fields are UI components, not data entities. They should stay in the features layer. Option 3 rejected — services are shared infrastructure consumed by all layers, same as core/ and ui/.
**Consequences**: Defines the import direction rules for all phases:
- shared/ imports: only OWL/libs
- entities/ imports: shared/
- features/ imports: shared/, entities/
- pages/ imports: all lower layers
**Revisit if**: A service is found that genuinely belongs to a higher layer (currently tree_processor is being fixed).

## ADR-004: Move useRecordObserver to fields/ — APPROVED

**Date**: 2026-03-05
**Phase**: 1
**Context**: `useRecordObserver` is defined in `model/relational_model/record_hooks.js` but used exclusively by field components (8 files) and 1 kanban record. It creates a fields→model coupling.
**Options Considered**:
1. Move to `fields/hooks/record_observer.js`
2. Keep in model/ and accept the coupling
3. Create an abstraction layer (observer interface) that model/ implements and fields/ consumes

**Decision**: APPROVED Option 1.
**Rejected alternatives**: Option 2 rejected because the hook's implementation depends only on `core/utils/reactive` (effect) and `core/utils/concurrency` (Deferred) — it has ZERO model internals dependency. It reads from `props.record` which is injected by the component layer. Option 3 rejected as over-engineering — the hook is simple enough to move directly.
**Consequences**: After move, `model/` has 0 inbound imports from `fields/` for this hook.
**Revisit if**: A new model-layer hook emerges that field components also need — at that point, consider a shared hooks directory.

## ADR-005: Extract Pure Tree Logic to core/domain/ — APPROVED

**Date**: 2026-03-05
**Phase**: 1
**Context**: `tree_processor_service.js` (a service) imports 7 items from `components/tree_editor/` (a component-layer directory). The imported items are pure data structure logic — no OWL, no UI.
**Options Considered**:
1. Move pure logic files to `core/domain/`
2. Keep in components/ and accept the service→component dependency
3. Make tree_processor a component-layer module instead of a service

**Decision**: APPROVED Option 1.
**Rejected alternatives**: Option 2 rejected — this is the only service→component dependency, and it's clearly a misplacement since the logic is pure. Option 3 rejected — tree_processor IS used as a service (via `useService("tree_processor")`), and services belong in services/ or shared/.
**Consequences**: 6 files move from components/tree_editor/ to core/domain/. Re-export shims added in old locations.
**Revisit if**: The tree_editor component needs to re-absorb this logic (unlikely — the split is clean).

## ADR-006: Defer State Machine for Form Save — DEFERRED

**Date**: 2026-03-05
**Phase**: 1
**Context**: The form save flow (CLEAN→DIRTY→VALIDATING→SAVING→RELOADING→CLEAN) is implicit in record.js, serialized through `model.mutex.exec()`.
**Options Considered**:
1. Introduce explicit state machine (XState-like or custom)
2. Keep implicit mutex-serialized flow
3. Add state tracking without full state machine (just a `saveState` enum property)

**Decision**: DEFERRED to Phase 8.
**Rejected alternatives for now**: Option 1 rejected — the mutex pattern works correctly and is well-tested. Adding a state machine would be a significant refactor with risk of introducing subtle timing bugs. No concrete bug or feature request motivates this change.
**Consequences**: The implicit state machine continues to work. Phase 8 can revisit.
**Revisit if**: A concrete bug caused by state confusion in the save flow is found (e.g., save triggered during save, discard during validation).

## ADR-007: Keep 28 Files as God Objects — APPROVED (selective)

**Date**: 2026-03-05
**Phase**: 1
**Context**: Of 38 files over 500 lines, 28 were analyzed and found to have high cohesion despite their size.
**Decision**: 10 files marked SPLIT, 28 marked KEEP TOGETHER.
**Key keepings**:
- `list_renderer.js` (1543 lines) — already decomposed via 9 hooks, OWL single-setup contract
- `pivot_model.js` (1037 lines) — deeply interleaved state, single domain concern
- `calendar_model.js` (1020 lines) — single domain concern
- `relational_model.js` (934 lines) — top-level orchestrator, cohesive
- `form_compiler.js` (760 lines) — clean visitor pattern
- `form_controller.js` (690 lines) — already well-structured
**Consequences**: These files are not split in Phase 6 unless future analysis reveals new seam lines.
**Revisit if**: Any of these files grows beyond 2000 lines, or a concrete testability problem emerges.
