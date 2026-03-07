# Web Module — JS Performance & Correctness Audit

> **Context**: Structural refactoring (Phases 1–11) and quality work (QUALITY_PLAN A–F)
> are complete. This audit targets a distinct orthogonal dimension: runtime correctness
> and performance in individual files. Every `.js` file in `static/src/` is audited
> exactly once. Findings are fixed in the same session as discovery.

---

## Audit Criteria

### Correctness (P0–P1)

| ID | Pattern | Severity |
|----|---------|----------|
| C-01 | Missing `await` on async calls — silent promise drop | P0 |
| C-02 | Unhandled rejection — no `.catch()` or `try/catch` around critical RPC | P0 |
| C-03 | Null/undefined dereference — accessing `.prop` without guard on nullable | P1 |
| C-04 | Stale closure — event handler or callback captures mutable outer variable | P1 |
| C-05 | Logic inversion — `!==`/`===` or `&&`/`\|\|` in wrong direction | P1 |
| C-06 | Missing `return` — async function implicitly returns `undefined` when callers use result | P1 |
| C-07 | Mutation during iteration — modifying Map/Set/Array while iterating it | P1 |
| C-08 | Off-by-one — incorrect `<`/`<=` or `>`/`>=` boundary | P1 |
| C-09 | Incorrect `this` binding — callback loses `this`, using non-arrow where arrow needed | P1 |
| C-10 | Domain/filter logic error — incorrect operator, wrong field, inverted condition | P1 |
| C-11 | Race condition — concurrent async ops without mutex/lock on shared state | P1 |
| C-12 | Type coercion bug — `==` instead of `===`, implicit number/string conversion | P1 |

### Performance (P2)

| ID | Pattern | Severity |
|----|---------|----------|
| P-01 | Expensive getter called in template without memoization (new array/object per render) | P2 |
| P-02 | O(n²) algorithm — nested loop over same collection | P2 |
| P-03 | Linear scan (Array.find/filter) where O(1) Map lookup is possible | P2 |
| P-04 | Unnecessary reactive allocation — `useState({})` on data derivable from props | P2 |
| P-05 | Missing `markRaw` on large non-reactive objects stored in reactive state | P2 |
| P-06 | Unbatched RPC calls in loop — N+1 pattern | P2 |
| P-07 | Missing debounce/throttle on high-frequency DOM events | P2 |
| P-08 | String concatenation in loop — should use `join()` or template accumulation | P2 |
| P-09 | Redundant recompute — reactive write of same value triggers unnecessary re-render | P2 |
| P-10 | Large synchronous computation on main thread blocking UI (>16ms budget) | P2 |

### Minor (P3)

| ID | Pattern | Severity |
|----|---------|----------|
| M-01 | Dead code — unreachable branch, always-false condition | P3 |
| M-02 | Redundant operation — double negation, identity comparison with default | P3 |
| M-03 | Inconsistent error message — wrong method name, stale description | P3 |

---

## Finding Format

Each finding in phase output files follows this template:

```
### FILE:LINE — [SEVERITY] [CATEGORY-ID] short title

**Code**:
\`\`\`js
// the problematic code (exact lines)
\`\`\`

**Problem**: one sentence explaining what is wrong and when it manifests.

**Fix**:
\`\`\`js
// the corrected code
\`\`\`
```

Findings are fixed immediately in the same session as discovery unless marked `SKIP`
with an explicit reason.

---

## Phase Plan

609 files across 14 sessions. Each phase covers one logical layer and produces
a `phase_pc[N]_output.md` file in `refactor/` with all findings and their dispositions.

| Phase | Directory scope | Files | Focus |
|-------|----------------|-------|-------|
| **PC-01** | `core/utils/` (flat + dom/ + dnd/) | 33 | Utility correctness: string/array helpers, hooks |
| **PC-02** | `core/` root + `core/browser/` + `core/errors/` | 25 | Browser API wrappers, error classes |
| **PC-03** | `core/network/` + `core/l10n/` + `core/py_js/` | 25 | RPC correctness, locale logic, Python parser |
| **PC-04** | `core/tree/` (16 files) + `model/` root (6 files) | 22 | Domain/tree pipeline, model factory |
| **PC-05** | `model/relational_model/` part 1 — data layer (14 files) | 14 | Cache, preprocessors, commands, field types |
| **PC-06** | `model/relational_model/` part 2 — list/record (13 files) | 13 | Record save/load, static/dynamic lists |
| **PC-07** | `search/` (31 files) | 31 | Query mutations, panel state, search model |
| **PC-08** | `services/` (31 files) | 31 | Action, dialog, notification, overlay |
| **PC-09** | `fields/` root + `fields/hooks/` (15 files) | 15 | Base field, formatters, hooks |
| **PC-10** | `fields/relational/` + `fields/specialized/` part 1 (35 files) | 35 | Many2one, x2many, properties |
| **PC-11** | `fields/specialized/` part 2 + remaining fields (60 files) | 60 | Date, binary, html, domain fields |
| **PC-12** | `components/` part 1 — domain_selector, expression_editor, dropdown (40 files) | 40 | Domain UI, dropdowns |
| **PC-13** | `components/` part 2 — tree_editor, record_selectors, misc (34 files) | 34 | Tree editor components |
| **PC-14** | `views/` root + `views/form/` + `views/view_components/` (26 files) | 26 | Form compiler, view base |
| **PC-15** | `views/list/` + `views/kanban/` (33 files) | 33 | List/kanban rendering |
| **PC-16** | `views/graph/` + `views/pivot/` + `views/calendar/` (26 files) | 26 | Chart rendering, model math |
| **PC-17** | remaining `views/` — settings, gantt, activity, etc. (55 files) | 55 | Remaining view types |
| **PC-18** | `webclient/` (45 files) | 45 | Action manager, router, menus |
| **PC-19** | `ui/` + `public/` + root files + `boot/` + `legacy/` (38 files) | 38 | App bootstrap, public API |

**Total**: 609 files across 19 phases.

---

## Session Continuity Protocol

Each session:
1. Read `PERF_CORRECTNESS_AUDIT.md` — confirm current phase
2. Read the files for the phase (use Bash `wc -l` to triage — read largest first)
3. For each file: scan against all criteria above
4. Fix findings immediately; document in `refactor/phase_pc[N]_output.md`
5. Update `PERF_CORRECTNESS_AUDIT.md`: mark phase complete, advance `## Current Phase`
6. Do NOT start next phase in same session unless significant context remains

## Current Phase

**PC-05 — `model/relational_model/` part 1 — data layer (14 files)** — NOT STARTED

## Completed Phases

| Phase | Files | Findings | Fixed | Skipped | Output |
|-------|-------|----------|-------|---------|--------|
| PC-01 | 38 | 8 (5 fixed + 3 skip) | 5 | 3 | `refactor/phase_pc01_output.md` |
| PC-02 | 20 | 6 (3 fixed + 3 skip) | 3 | 3 | `refactor/phase_pc02_output.md` |
| PC-03 | 24 | 1 (1 fixed + 0 skip) | 1 | 0 | `refactor/phase_pc03_output.md` |
| PC-04 | 22 | 4 (4 fixed + 0 skip) | 4 | 0 | `refactor/phase_pc04_output.md` |

---

## Global Findings Registry

Findings that affect patterns used across multiple files (fix everywhere, not just discovery site):

*(empty — populated as phases complete)*

---

## Skip Registry

Patterns that look wrong but are intentional — read before re-auditing:

*(empty — populated as phases complete)*
