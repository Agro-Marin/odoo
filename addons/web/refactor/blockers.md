# Blockers

No blockers identified during Phase 1 analysis.

## Potential Risks for Future Phases

### Risk 1: search_model.js DomainSelectorDialog import
**Phase affected**: 4
**Description**: `search_model.js` directly imports `DomainSelectorDialog` from `@web/components/domain_selector_dialog`. The `spawnCustomFilterDialog` method uses `this.dialog.add(DomainSelectorDialog, ...)`. Refactoring this to a callback injection requires understanding all callers of SearchModel and how they'd provide the dialog spawner.
**Mitigation**: The SearchModel already receives `dialog` service via `useService("dialog")`. The fix is to lazy-import DomainSelectorDialog within the method body or pass it as a config option. Not blocking, just requires careful handling.

### Risk 2: ControllerComponent extraction from action_service
**Phase affected**: 6c
**Description**: The dynamically-defined `ControllerComponent` (145 lines inside `_updateUI`) closes over 5 variables from the `makeActionManager` scope: `controllerStack`, `env`, `dialog`, `nextDialog`, and the `id` counter. Extracting it to a standalone file requires passing these as props or context.
**Mitigation**: Use OWL's `useSubEnv` to inject the action manager state, or pass via props. Prototype the extraction before committing.

### Risk 3: Asset bundle ordering in Phase 5
**Phase affected**: 5
**Description**: Moving files from `components/tree_editor/` to `core/domain/` may affect the load order in asset bundles. The manifest uses `"web/static/src/model/**/*"` which loads before `"web/static/src/views/**/*"`. If `core/domain/` files are loaded before their consumers, this should be fine. But if any consumer relies on module load order (unlikely with ES modules, but possible with side effects), this could break.
**Mitigation**: Verify that all moved files have no top-level side effects. Run full test suite after the move.
