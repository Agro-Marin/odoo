# Phase 4+11 Audit Report: Boot, Public, Legacy

> **Date**: 2026-03-08
> **Files audited**: ~20 files (env.js, session.js, boot/, service_worker.js,
> public/, legacy/, module_loader.js)
> **Findings**: 3 High, 13 Medium, 14 Low

---

## Fixes Applied

| # | File | Fix |
|---|------|-----|
| 1 | `service_worker.js:92` | Base case guard prevents infinite recursion when homepage not cached |
| 2 | `env.js:139` | try/catch around `service.start()` — one broken service no longer crashes all |
| 3 | `public_root.js:108-111` | Null check on scrollTop regex match |

## Remaining Issues

### High (flagged)
- `service_worker.js:9,67-68` — Session info stored in RAM leaks credentials.
  Cached pages served offline contain full session data. Only cleared on explicit
  logout, not session expiry.
- `service_worker.js:31` — Regex-based JSON extraction (`.*?` with `/s`) can
  truncate on `};` inside string values.
- `database_manager.js:36` — `Modal` used as undefined global (Bootstrap dependency).

### Medium
- `env.js:145` — `services[name] = val || null` treats 0, "", false as null.
- `start.js:50` — `Component.env = env` global static mutation.
- `service_worker.js:70-71` — Hardcoded `@@@session_info_secret@@@` sentinel.
- `service_worker.js:75` — Response Content-Length incorrect after body modification.
- `show_password.js:8-25` — `showPassword` never explicitly initialized.
- `datetime_picker.js:28` — Accesses service without dependency declaration.
- `public_component_interaction.js:12` — `JSON.parse` of untrusted props attribute.
- `public_root.js:63-83` — Monkey-patching InteractionService prototype.
- `database_manager.js:37` — Accesses Bootstrap private `_element` API.
- `public_widget.js:365` — Reads `Component.env` before boot may complete.
- Code duplication: `makeAsyncHandler` in both utils.js and minimal_dom.js.

### Architecture Notes
- Two parallel public widget systems coexist (Interaction + PublicWidget).
  Legacy bridge via monkey-patching. 7 consumers remain outside web module.
- Module loader is well-designed: synchronous, no race conditions, has cycle detection.
- Service dependency resolution is correct: topological sort with fallback cycle detection.
- Session capture is atomic (synchronous module evaluation).
