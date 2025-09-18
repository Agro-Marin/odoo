# Refactoring State — Last Updated: 2026-03-05

## Current Phase: 4 — Decouple Fields from Model (COMPLETE)
## Next Action: Execute Phase 5 — Fix Service/Component Inversion (extract pure tree logic to core/domain/)

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
  - Re-export shim: model/relational_model/record_hooks.js (zero consumers — all updated to canonical path)
  - Updated 9 web imports: 8 fields/ files + 1 views/kanban_record.js → new path
  - Updated 12 core addon imports + 11 enterprise imports + 1 addons_custom import → canonical @web/fields/hooks/record_observer
  - DomainSelectorDialog: removed import from search_model.js, injected via with_search.js services
  - Boundary violation #4 resolved: fields/ no longer imports useRecordObserver from model/
  - Boundary violation #8 resolved: search_model.js no longer imports UI dialog component

## Not Started
- [ ] Phase 5: Fix Service/Component Inversion
  - Extract pure tree logic to core/domain/
  - Target: 0 imports from @web/components in services/ (except debug menu dropdown)
- [ ] Phase 6: Decompose God Objects (10 sub-phases, one PR each)
- [ ] Phase 7: Directory Restructure (full FSD)
- [ ] Phase 8: New Abstractions

## Plan Deviations
- Phase 2: Plan listed `fields/parsers.js` as needing update — it does not import x2ManyCommands. Actual fields/ files updated: `fields/relational/x2many/x2many_field.js` and `fields/specialized/user_groups/res_user_group_ids_field.js` (8 total imports updated, matching plan count)
- Phase 3: Plan estimated 10 files and constructor injection. Actual: 3 files, no constructor changes. `current_company_id` was derivable from existing config data, and the `user` param to `buildSampleORM` was dead code. `Object.create(orm)` replaced `new ORM(user)` with cleaner prototype delegation.

## Key Metrics
- Files analyzed: 612
- God objects (>500 lines): 38
- Files to split: 10
- Files to keep: 28
- Boundary violations: 9 (4 resolved: #1, #4, #8, plus model→services)
- Import paths updated (Phases 2-4): 59 total (8+10+8 x2ManyCommands, 9+12+11+1 useRecordObserver)
- Import paths to update (remaining phases): ~60 estimated
- Custom error classes: 28
- JSDoc coverage: 81% (494/612 files)
- Index.js files: 0 (to be created in Phase 7)
