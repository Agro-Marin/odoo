# Web JS Quality Plan

> **Living document** — tracker + standards + dead ends log.
> Updated after every session. Check this before starting any JS work in `web/`.

---

## Quick Status

| Phase | Area | Groups | Files | Lines | Status |
|-------|------|--------|-------|-------|--------|
| 0 | Infrastructure | — | ~5 | ~900 | `[X]` |
| 1 | core/ | 01–09 | 100 | 19K | `[X]` |
| 2 | model/ | 10a–10e | 33 | 8.7K | `[X]` |
| 3 | fields/ | 11–15 | 110 | 15.7K | `[X]` |
| 4 | search/ | 16a–16b | 31 | 7.4K | `[X]` |
| 5 | services/ | 17a–17e | 31 | 5.4K | `[X]` |
| 6 | ui/ + components/ | 18–23 | 94 | 15.3K | `[X]` |
| 7 | views/ | 24–31 | 140 | 26.7K | `[X]` |
| 8 | webclient/ + public/ | 32–35 | 50 | 8.4K | `[X]` |

**Status symbols:** `[ ]` not started · `[A]` audited · `[P]` plan ready · `[W]` in progress · `[X]` done · `[-]` skip

---

## How to Use This Document

### Running an Audit Agent

For each group, spawn a single Sonnet agent with this template:

```
You are auditing the [GROUP NAME] functional area of the Odoo 19 web module.
Your job is to read EVERY file listed, understand the FULL picture of how they
work together, and produce a structured findings report.

Files to read (in this order):
  [list files from smallest to largest — build context incrementally]

For each file AND for the group as a whole, report findings under these labels:
  BUG   — actual correctness bugs, wrong logic, broken edge cases
  TYPE  — missing/wrong JSDoc types, missing @ts-check, inaccurate shapes
  PRIV  — properties that should be #private (non-patchable, non-OWL-reactive state)
  SIZE  — functions >80 lines that need extraction
  DEAD  — dead code, unused exports, commented-out code, unreachable branches
  PERF  — hot-path allocations, missing memoization, O(n²) loops, unnecessary reactive deps
  PAT   — pattern inconsistency vs other files in same layer or same group
  TEST  — missing test cases, untestable design, needed test infrastructure
  ERR   — missing error handling, silent failures, swallowed errors, no input validation
  API   — public API surface confusion: accidentally exported internals, naming ambiguity
  NAME  — misleading names, bad abbreviations, single-letter variables outside loops
  STRUCT — wrong file (should move), should be split, should be merged with another file

Format each finding as:
  [LABEL] filename.js:line — brief description
  Impact: [low|medium|high|critical]
  Fix: what to do

End with a GROUP SUMMARY:
  - Cross-file patterns that are wrong
  - Duplication across files that should be extracted
  - Missing abstractions that multiple files are reinventing
  - Recommended implementation order for fixes
```

### Implementing Fixes

After reviewing the agent report:
1. Update the file's status to `[P]` and list the top-5 prioritized findings
2. Implement fixes file-by-file, highest impact first
3. Mark `[X]` when done; add any dead ends discovered to the Dead Ends Log

---

## Quality Standards

These define "done" for every file. Every finding must be evaluated against these.

### JS Doc Standards

```js
// @ts-check  ← REQUIRED on every source file (not tests)

/**
 * Brief one-line description of what the module exports/does.
 * @module @web/core/registry
 */

/**
 * Does X given Y.
 *
 * @param {string} key - What the key represents
 * @param {Record<string, number>} options - Options object
 * @returns {boolean} True if X, false if Y
 */
export function doThing(key, options) { ... }
```

Rules:
- Every **exported** function/class/constant: full `@param` + `@returns` with types
- `{any}` is allowed only with a comment: `{any} /* reason: ... */`
- `{object}` is never allowed — use a specific `@typedef` or inline shape
- `@typedef` for any shape used in more than one place
- Every file that does not have `// @ts-check`: add it (Phase 0 codemod)
- No `@ts-ignore` without a comment explaining the exception

### Private Fields (#)

```js
class MyService {
    // OK — internal cache, never patched, not OWL reactive
    #cache = new Map();
    #initialized = false;

    // NOT OK — OWL Proxy cannot intercept #field access
    // NOT OK — patch() cannot override #methods
    // NOT OK — sub-registries access this
    content = {};
}
```

Rule: `#private` is allowed for:
- Internal caches set once in constructor or `setup()`
- State that is provably not accessed by OWL reactivity
- State that no addon or test should ever patch or read directly
- Constants that are computed once

The ESLint ban on `PrivateIdentifier` must be lifted in Phase 0 before any `#field` is introduced.

### Method Length

- **Hard limit**: 80 lines per function body
- **Target**: ≤40 lines for most functions
- **Exception**: `switch` statements over enums — each `case` counts as 1 line
- Extraction strategy: prefer named helper functions over inline comments

### Error Handling

```js
// WRONG — silent failure
try {
    result = JSON.parse(raw);
} catch {
    result = {};
}

// RIGHT — log and rethrow, or handle specifically
try {
    result = JSON.parse(raw);
} catch (e) {
    console.error("Failed to parse config JSON:", e);
    throw new ConfigError(`Invalid JSON in config: ${e.message}`, { cause: e });
}
```

Rule: No empty `catch` blocks. Every `catch` either re-throws, logs, or returns a typed fallback with a comment.

### API Surface Clarity

- Anything that should not be used outside the file: don't export it
- Anything that IS part of the public API: JSDoc `@public` + full type
- `@internal` comment for things exported only for tests
- No barrel re-exports that hide the origin (`export * from './thing'` is a smell unless it IS the barrel)

### Pattern Consistency

Each layer has established patterns — these must be consistent:

| Layer | Pattern |
|-------|---------|
| `core/` | Pure functions where possible, no OWL imports |
| `model/` | Plain objects, no OWL components, reactive via `useState` at boundary |
| `services/` | Factory functions returning service object, registered via `registry.category("services")` |
| `components/` | OWL class components (or functional where stateless), `static props = {...}` |
| `views/` | Controller+Renderer+Model triple, arch parser separate |
| `fields/` | Extends base field, `static type`, `static displayName`, `static supportedTypes` |

### Naming

- No single-letter variables outside `for` loop indices
- No abbreviations that aren't universally known (`btn` ok, `cntrlr` not ok)
- Boolean variables: `is*`, `has*`, `can*`, `should*`
- Functions: verb-first (`fetchRecords`, `computeDomain`, `parseArch`)
- Constants: `UPPER_SNAKE_CASE` for true module-level constants

### Testing Standards

- Every pure function: unit test in corresponding `tests/` file
- Every service: integration test that mounts it in a mock environment
- God functions extracted to helpers: the new helpers must have tests
- Test infra improvements go in `quality/TEST_INFRA_PLAN.md` (separate doc, created as needed)

---

## Dead Ends Log

Document every path that was explored and found to be a dead end.
**Purpose**: prevent re-discovery in future sessions.

Format:
```
### DE-NNN: Short Description
**Date**: YYYY-MM-DD
**Attempted**: what we tried to do
**Why it fails**: concrete technical reason
**Alternative**: what to do instead (if any)
```

---

### DE-001: Enable `strictNullChecks` globally in jsconfig.json
**Date**: 2026-03-07
**Attempted**: Add `"strictNullChecks": true` to `jsconfig.json` to catch null-dereference bugs
**Why it fails**: Causes thousands of type errors across all 632 files simultaneously because the codebase assumes `field | null` is just `field` in hundreds of places (ORM returns, optional props, conditional state). Unfixable in one pass.
**Alternative**: Enable per-file via `// @ts-check` + explicit `if (!x) return` guards as we touch each file. Or create a separate strict tsconfig for newly written files.

---

### DE-002: Enable `noImplicitAny` globally in jsconfig.json
**Date**: 2026-03-07
**Attempted**: Add `"noImplicitAny": true` to catch untyped function parameters
**Why it fails**: Same as DE-001 — thousands of violations. OWL component lifecycle methods (`setup()`, `render()`, etc.) rely on implicit `any` for props.
**Alternative**: Per-file approach — when auditing a file, add explicit JSDoc types to all parameters. Don't enable globally.

---

### DE-003: Migrate source files from `.js` to `.ts`
**Date**: 2026-03-07
**Attempted**: Full TypeScript migration for stronger type guarantees
**Why it fails**: (a) Would require changing module aliases in `jsconfig.json`, `eslint.config.mjs`, and all `@web/*` import paths. (b) OWL's type definitions assume JS-style class decorators. (c) Breaks build pipeline assumptions in Odoo's asset bundler. (d) Enterprise modules and addons_custom/ all import `@web/*` paths assuming `.js` files.
**Alternative**: Stay with JSDoc + `// @ts-check`. Stricter than nothing, no migration cost.

---

### DE-004: Convert OWL class components to functional components
**Date**: 2026-03-07
**Attempted**: Functional components are simpler and avoid `this` confusion
**Why it fails**: The `patch()` mechanism works by replacing methods on class prototypes. Functional components cannot be patched. Since Odoo's entire addon extension system depends on `patch()`, converting components would break every addon that extends a web component.
**Alternative**: Keep class components. Use functional components only for NEW stateless leaf components that no addon will ever need to extend.

---

### DE-005: Make `Registry.content` private (`#content`)
**Date**: 2026-03-07
**Attempted**: Encapsulate the registry's internal `content` map to prevent direct manipulation
**Why it fails**: At least 12 files in `addons_custom/` and several enterprise modules directly access `.content` for performance (bypassing `getAll()` iteration). Tests also spy on `.content`. Breaking this would require auditing the entire ecosystem.
**Alternative**: Add a `@internal` JSDoc comment. When eventually removing direct access, search the full monorepo and provide migration period.

---

### DE-006: Remove the `PrivateIdentifier` ESLint ban globally
**Date**: 2026-03-07
**Attempted**: Allow `#field` syntax everywhere
**Why it fails**: Not actually a dead end — but must be done carefully. The ban exists because OWL's reactive Proxy intercepts property get/set by key name, which doesn't work with private fields. If you put an OWL `useState`-tracked property behind `#`, the component will not react to changes.
**Alternative**: Lift the ban with a conditional — allow `#field` only for non-reactive state (caches, flags). Add a comment rule: `// @private — not OWL-reactive, not patchable`. When lifting the ban in eslint.config.mjs, document this constraint explicitly.

---

### DE-007: Add `eslint-plugin-jsdoc` with `jsdoc/require-param` globally
**Date**: 2026-03-07
**Attempted**: Enforce that every function has JSDoc with typed params
**Why it fails**: Turning it on globally fails on hundreds of files immediately. Internal helpers, callbacks, and OWL lifecycle methods don't need the same level of docs.
**Alternative**: Enable per-group as each group passes audit. Use `// eslint-disable-next-line jsdoc/require-param` sparingly with a reason comment.

---

### DE-008: Audit `emoji_data.js` (36K lines)
**Date**: 2026-03-07
**Attempted**: Include in code quality audit
**Why it fails**: It's a generated data blob (Unicode emoji database), not authored code. There is nothing to improve architecturally.
**Alternative**: Skip entirely. Exclude from all audits and codemods.

---

## Phase 0: Infrastructure

**Goal**: Fix tooling before touching any source files. Anything done here multiplies across all 600+ files.

**Status**: `[X]` — All 4 sub-tasks complete as of 2026-03-07.

### 0.1 ESLint Rule Additions

Add these rules to `eslint.config.mjs` in the main `rules` block:

| Rule | Config | Rationale |
|------|--------|-----------|
| `object-shorthand` | `["error", "always"]` | `{ fn: fn }` → `{ fn }` |
| `prefer-template` | `"error"` | No `"x" + y` string concat (except logger %) |
| `no-lonely-if` | `"error"` | `else { if (...) }` → `else if` |
| `yoda` | `"error"` | No `if (42 === x)` |
| `eqeqeq` | `["error", "always", { null: "ignore" }]` | No `==` except null checks |
| `no-useless-rename` | `"error"` | `const { a: a }` → `const { a }` |
| `no-useless-computed-key` | `"error"` | `{ ["a"]: 1 }` → `{ a: 1 }` |
| `prefer-rest-params` | `"error"` | No `arguments` object |
| `prefer-spread` | `"error"` | No `.apply(null, args)` |
| `no-else-return` | `"error"` | Remove redundant `else` after `return` |
| `logical-assignment-operators` | `"error"` | `x = x \|\| y` → `x \|\|= y` |
| `no-implicit-coercion` | `["error", { boolean: false }]` | No `+"3"`, `"" + x` |
| `no-prototype-builtins` | `"error"` | `obj.hasOwnProperty` → `Object.hasOwn(obj,...)` |

Also: remove `"no-restricted-syntax": ["error", "PrivateIdentifier"]` from the main rules and replace with a comment rule (see DE-006).

**Status**: `[X]` — All 13 rules added to `eslint.config.mjs`. ESLint auto-fixed 402 violations.
Remaining 77 fixed manually across 40+ files. Zero violations as of 2026-03-07.

### 0.2 JSDoc Header Codemod

Write a script that adds `// @ts-check\n` to every `.js` file in `static/src/` that doesn't have it. Run with `node quality/scripts/add_ts_check.js`.

Estimated files missing `// @ts-check`: ~400 (registry.js has it, most others don't).

Script created at `quality/scripts/add_ts_check.js`. Run it to apply.

**Status**: `[X]` — Applied 2026-03-07. 3 files added (`module_loader.js`, `service_worker.js`,
`session.js`). 598 already had it. 8 skipped (emoji_data, legacy, libs, tests).

### 0.3 Test Infrastructure Baseline

**Documented 2026-03-07.**

Current state:
- **Test runner**: Hoot (`@odoo/hoot`) — browser-based, not Node. Tests must run inside Odoo dev server.
- **Test location**: `static/tests/` mirrors `static/src/` structure. 322 `.test.js` files.
- **Helpers available** (all in `static/tests/_framework/`):
  - `makeEnv` / `startServices` — full OWL env with all services
  - `MockServer` / `makeMockServer` — ORM mock with model definitions
  - `env_test_helpers.js` — per-test env isolation with registry cleanup
  - `component_test_helpers.js` — mount/unmount helpers
  - `dom_test_helpers.js` — click, fill, hover, keyboard helpers
  - `mock_browser.hoot.js`, `mock_session.hoot.js`, `mock_user.hoot.js`
  - `view_test_helpers.js`, `webclient_test_helpers.js`, `search_test_helpers.js`
  - `patch_test_helpers.js` — clean patch/unpatch per test
- **Coverage**: No automated coverage tooling found. Manual coverage only.
- **How to run**: Odoo dev server with `--dev=all`, open `http://localhost:8069/web/tests` in browser.
  Or: `./core/odoo-bin -c ./conf/odoo.conf -d dev_db --dev=all` then navigate to test runner.

Tasks:
- [x] Determine how to run the test suite locally
- [x] Identify available test helpers
- [ ] Measure baseline test count / pass rate before quality work begins
- [ ] Create `quality/TEST_INFRA_PLAN.md` if test infrastructure gaps are found during audit

**Status**: `[X]` — Baseline documented. Infrastructure is solid; no blockers for quality work.

### 0.4 Import Sort Codemod

Run `eslint --fix` with `simple-import-sort` on all files to normalize import order before audits (prevents noise in audit reports).

```bash
cd /home/marin/Odoo/core && npx eslint 'addons/web/static/src/**/*.js' --fix
```

**Status**: `[X]` — Applied 2026-03-07. All `web/static/src` imports normalized via `simple-import-sort`.

---

## Phase 1: core/ — Shared Infrastructure Layer

**Constraint**: `core/` must NOT import from `fields/`, `views/`, `search/`, `webclient/` (enforced by ESLint). Pure utility code.

### Group 01 — Module System & Bootstrap

**Files** (read in this order):
```
boot/               (2 files, ~80 lines total)
module_loader.js    (full file — not linted by ESLint, bootstrap IIFE)
env.js
session.js
service_worker.js
```

**Key questions for the agent**:
- `module_loader.js` uses an IIFE (`(function(odoo){...})`). Is this still necessary or can it be a proper ESM module? (Likely necessary — bootstraps before ESM is available)
- How does `env.js` compose services? Is the composition order deterministic?
- `session.js`: what shape is the session object? Is it fully typed?
- `service_worker.js`: fetch strategy — is it correct? Does it handle offline edge cases?

**Status**: `[X]` — Audited 2026-03-07. 8 fixes applied (see below).

**Top findings (implemented)**:
1. **[CRITICAL] main.js:13** — `startWebClient()` unhandled promise → added `.catch()` with console.error
2. **[CRITICAL] service_worker.js:97** — `replaceAll(placeholder, null)` inserts literal `"null"` after logout → guard with `sessionInfo !== null`
3. **[HIGH] service_worker.js:93** — infinite recursion in `readDataOnCache` when `/odoo` not cached → added base case `if (url === homepageURL) return undefined`
4. **[HIGH] service_worker.js:42** — recursive `getTextFromResponse` with string concat → replaced with `response.clone().text()`
5. **[HIGH] env.js:139** — service `start()` errors had no service name context → wrapped in try/catch with `"Service X failed to start"` message
6. **[BUG] env.js:145** — `val || null` treated falsy service returns as null → fixed to `val ?? null`
7. **[ERR] service_worker.js:121** — `storeDataOnCache` fire-and-forget → added `.catch(console.warn)`
8. **[BUG] service_worker.js:12** — install fetch failure aborted SW install → added `.catch(() => null)` (non-fatal)

**Remaining findings (deferred)**:
- `module_loader.js`: `findJob()` O(n×m) scan — topological sort optimization (PERF/medium)
- `module_loader.js`: duplicate silent suppression — add debug-mode `console.warn` (BUG/medium)
- `module_loader.js`: public fields should be `#private` where not OWL-reactive (PRIV/low)
- `env.js:110`: `_startServices` 88 lines — extract `_diagnoseUnstartedServices` (SIZE/medium)
- `env.js`: `customDirectives`/`globalValues` belong in dedicated `directives.js` (PAT/medium)
- `session.js`: add `@typedef SessionInfo` with all known fields (TYPE/medium)
- `service_worker.js`: missing `activate` handler — old caches accumulate (DEAD/medium)
- `service_worker.js`: cache name has no version — stale caches survive SW updates (NAME/medium)
- `service_worker.js:32`: regex `extractSessionInfo` fragile — couples SW to HTML template syntax (STRUCT/high)
- `start.js:17`: Chrome meta tag DOM mutation at module eval time — move inside function (STRUCT/medium)
- `start.js:65`: FIXME comment `delete odoo.debug` — resolve or remove (DEAD/medium)

### Group 02 — Core Utilities (General)

**Files** (~25 files, read by sub-area):
```
core/utils/collections/arrays.js       (281 lines)
core/utils/collections/cache.js
core/utils/format/numbers.js           (325 lines)
core/utils/format/strings.js           (284 lines)
core/utils/format/binary.js
core/utils/format/colors.js            (496 lines)
core/utils/dom/xml.js
core/utils/dom/html.js                 (290 lines)
core/utils/dom/ui.js                   (213 lines)
core/utils/dom/scrolling.js            (212 lines)
core/utils/dom/classname.js
core/utils/dom/events.js
core/utils/dom/dvu.js
core/utils/functions.js
core/utils/timing.js                   (218 lines)
core/utils/render.js
core/utils/reactive.js
core/utils/patch.js
core/utils/hooks.js                    (331 lines)
core/utils/macro.js                    (276 lines)
core/utils/components.js
core/utils/virtual_grid.js
core/utils/pdfjs.js
core/utils/indexed_db.js               (260 lines)
core/utils/decorations.js
core/utils/dependency_graph.js
core/utils/order_by.js
```

**Key questions for the agent**:
- `arrays.js`: does it duplicate anything in native `Array` methods? Are there O(n²) implementations?
- `format/colors.js` (496 lines): is this too large? Does it overlap with `core/colors/colors.js` (222 lines)?
- `reactive.js`: how does it relate to OWL's built-in reactivity? Is this a wrapper or alternative?
- `patch.js`: full audit — this is critical infrastructure. Are there edge cases in prototype chain walking? Does it handle class inheritance correctly? Memory leaks?
- `hooks.js` (331 lines): are all hooks actually used? Any deprecated patterns?
- `indexed_db.js` (260 lines): error handling audit — IndexedDB has many failure modes
- `macro.js` (276 lines): document what a "macro" is in this context — unclear from name alone

**Status**: `[X]` — Audited + 10 fixes applied 2026-03-07.

**Top findings (implemented)**:
1. **[CRITICAL] colors.js:329** — `mixCssColors` destructures `rgba1.red` without null-check; `convertCSSColorToRgba` returns `false` for invalid input → added `if (!rgba1 || !rgba2) return ""`
2. **[HIGH] objects.js:34** — `deepEqual` has no circular reference guard → crashes with infinite recursion on self-referential objects → replaced one-liner with function using WeakMap `_seen` cycle tracker
3. **[HIGH] objects.js:127** — `deepMerge` returns `undefined` when neither arg is a plain object → violates docstring "extension wins, fallback to target" semantics → fixed to `extension !== undefined ? extension : target`
4. **[HIGH] patch.js:125** — double-unpatch corrupts prototype chain: closure captures `description` by reference; second call finds `patchDescriptions` empty and re-applies stale extensions → added `if (!description.extensions.has(extension)) return` guard
5. **[HIGH] indexed_db.js:192** — `request.onerror` resolves (not rejects) the promise, calling `callback()` without a db → callers cannot detect failure → changed to `reject(error || new Error("IDB database open failed"))`
6. **[HIGH] scrolling.js:97,116** — `scrollend` event not supported in Safari <16.4 / Firefox <109 → promise never resolves → added `setTimeout(resolve, 2000)` fallback in both call sites
7. **[MED] files.js:58** — `JSON.parse(fileData)` unguarded; malformed server response throws uncaught SyntaxError → wrapped in try/catch
8. **[MED] files.js:88** — `canvas.getContext("2d")` result used without null check → crash if context unavailable → added null guard with `reject()`
9. **[MED] macro.js:157-166** — `launchTimer` used `delay()` with no cancellation; setTimeout leaked after `executeStep` won the race → replaced with `new Promise` + `clearTimeout` via `.finally(cancelTimer)`
10. **[BUG] macro.js:92-95** — `waitUntil` scheduled an extra rAF frame after `resolve()` (no `return`) → added `return` after `resolve(result)`

**Remaining findings (deferred)**:
- `colors.js` (496 lines): overlaps with `core/colors/colors.js` (222 lines) — consolidate (STRUCT/medium)
- `hooks.js:195` `useService`: no assertion that service exists → returns `undefined` silently (ERR/medium)
- `indexed_db.js`: quota error in `_write`/`_delete` not handled like in `_read` (ERR/medium)
- `macro.js`: `waitUntil` still leaks rAF when `launchTimer` wins race (no AbortSignal) (PERF/medium)
- `reactive.js`: `KeepLast` / `Mutex` reimplementations may duplicate `@web/core/utils/concurrency` (PAT/low)
- `patch.js`: `findAncestorPropertyDescriptor` does prototype chain walk inside `patch()` hot path (PERF/low)
- `arrays.js`: already uses `Set` for `unique()` — no issue found

### Group 03 — Drag & Drop System

**Files** (read in dependency order):
```
core/utils/dnd/draggable_hook_builder_utils.js   (373 lines)
core/utils/dnd/draggable_hook_builder.js          (868 lines — LARGEST IN core/)
core/utils/dnd/draggable_hook_builder_owl.js
core/utils/dnd/draggable.js
core/utils/dnd/sortable.js                        (368 lines)
core/utils/dnd/sortable_owl.js
core/utils/dnd/nested_sortable.js                 (446 lines)
```

**Key questions for the agent**:
- `draggable_hook_builder.js` at 868 lines: what is the core abstraction? Can it be split?
- Relationship between `draggable_hook_builder.js`, `draggable_hook_builder_owl.js`, and `draggable.js` — are these three levels of abstraction or three implementations of the same thing?
- Performance: pointer event listeners — are they properly cleaned up on component destroy?
- `nested_sortable.js` vs `sortable.js`: what's the overlap? Should nested extend sortable or is it a separate implementation?
- Touch events: are they handled? Mobile drag support?

**Status**: `[X]` — Audited + 7 fixes applied 2026-03-07.

**Top findings (implemented)**:
1. **[HIGH] nested_sortable.js:170-179** — `_getDeepestChildLevel` uses `querySelectorAll("ul li")` (descendant combinator), causing O(2^d) recursion on nested structures → fixed to `:scope > ul > li` (direct children only), now O(n)
2. **[HIGH] sortable.js:362** — `delete sortableParams.setupHooks` mutates caller's object → fixed with `const { setupHooks, ...rest } = sortableParams`
3. **[MEDIUM] nested_sortable.js:189** — `list.parentNode.closest(...)` crashes if `parentNode` is null → added optional chaining `?.`
4. **[MEDIUM] nested_sortable.js:240** — `getChildList` used `querySelector("ul")` matching ANY descendant list, not the direct child → fixed to `:scope > ${ctx.listTagName}`
5. **[MEDIUM] draggable_hook_builder.js:793** — `touchDelay = delay || touchDelay` silently discards explicit `touchDelay` when `delay` is set → fixed with `??` operator so `touchDelay` takes precedence
6. **[MEDIUM] nested_sortable.js:25** — `isAllowed` JSDoc documented 1-arg signature but implementation calls it with 2 args → corrected typedef; simplified default to `() => true`
7. **[LOW] nested_sortable.js:290,308** — `(-1) ** ctx.isRTL` idiom (mathematically correct, behaviorally fine) but non-obvious → refactored to explicit `const rtlSign = ctx.isRTL ? -1 : 1`

**Remaining findings (deferred)**:
- `nested_sortable.js:156-162` — hardcoded `.o_navbar`/`.o_action_manager` in generic utility (architectural violation; needs config param) (STRUCT/high)
- `draggable_hook_builder.js:116-868` — ~700 line monolithic closure; split into state machine, effects, geometry modules (SIZE/high)
- `draggable_hook_builder_utils.js:139` — `elCache` module-level global, never GC'd; leaks `HTMLElement` refs across drags (PERF/medium)
- `draggable_hook_builder_utils.js:266` — `addStyle` silently skips cleanup when element already cached (BUG/medium)
- `draggable_hook_builder_owl.js` + `sortable_owl.js` — duplicate `setupHooks` object; extract `makeOwlSetupHooks()` (PAT/medium)
- `sortable.js:150-187` — `siblingArray` rebuilt from DOM on every `pointerenter` → O(n²) per drag (PERF/medium)
- `nested_sortable.js:343-354` — hardcoded 10px/15px dead zone (5px) for drop hotspot (STRUCT/medium)
- `draggable_hook_builder.js:264-268` — `getElementsByTagName("iframe")` on every dragStart (PERF/low)

### Group 04 — Localization & Dates

**Files**:
```
core/l10n/localization.js
core/l10n/translation.js
core/l10n/utils.js
core/l10n/utils/format_list.js
core/l10n/utils/locales.js
core/l10n/utils/normalize.js              (210 lines)
core/l10n/date_serialization.js
core/l10n/date_utils.js
core/l10n/dates.js                         (433 lines)
core/l10n/time.js                          (307 lines)
```

**Key questions for the agent**:
- Date serialization: what format is used? ISO 8601? Odoo-specific format? Are edge cases (DST, midnight, leap years) handled?
- Relationship between `dates.js`, `date_utils.js`, and `date_serialization.js` — is the split logical?
- `time.js` (307 lines): what does this add beyond `dates.js`?
- Translation: how are plurals handled? RTL languages?
- `normalize.js` (210 lines): is Unicode normalization for search correct? NFC vs NFD vs NFKC?

**Status**: `[X]` — Audited + 4 fixes applied 2026-03-07.

**Top findings (implemented)**:
1. **[HIGH] format_list.js** — `new Intl.ListFormat(locale, style)` constructed on every call; constructor is expensive → added module-level `Map` cache keyed by `"${locale}|${style}"` (O(1) repeated calls)
2. **[HIGH] time.js:constructor** — `_is24HourFormat` and `_isMeridiemFormat` were cached at construction time; locale changes after construction silently used stale format → removed cached fields; `toString()` now calls `is24HourFormat()` / `isMeridiemFormat()` dynamically
3. **[MEDIUM] normalize.js:outer-loop** — outer loop bound was `flattenSrcLength - normalizedSubstr.length` (skips tail of source) → fixed to `normalizedSrc.length` so the full source is searched
4. **[MEDIUM] date_utils.js** — `value.filter(Boolean).sort()` used JS string comparison for `DateTime` objects (undefined behavior) → replaced with explicit `(a, b) => (a < b ? -1 : a > b ? 1 : 0)` comparator

**Remaining findings (deferred)**:
- `dates.js:250-433` — `parseDatetime` / `parseDate` mega-function (130+ lines): split DST normalization, format detection, and Luxon bridge into separate helpers (SIZE/high)
- `translation.js` — plural rule evaluation uses `eval`-equivalent string function compilation; no sanitization of server-provided plural rules (BUG/high — server-trust boundary)
- `date_utils.js` — `getQuarterValues` returns raw month offsets; no documentation of why Q1 starts at month index 0 in some locales (TYPE/medium)
- `date_serialization.js` — `serialize_datetime` always serializes in UTC; DST-aware local serialization missing (STRUCT/medium)
- `normalize.js:140-190` — inner loop is O(n×m) with no short-circuit on first mismatch (PERF/medium)
- `locales.js` — static map of 170+ locale codes; no fallback chain if exact locale not found (PAT/low)

### Group 05 — Python Expression Evaluator

**Files** (read in pipeline order: lex → parse → interpret):
```
core/py_js/py_utils.js
core/py_js/py_builtin.js
core/py_js/py_tokenizer.js               (335 lines)
core/py_js/py_parser.js                  (412 lines)
core/py_js/py_interpreter.js             (507 lines)
core/py_js/py.js                          (entry point)
core/py_js/py_date_helpers.js            (270 lines)
core/py_js/py_timedelta.js
core/py_js/py_date.js                    (574 lines)
```

**Key questions for the agent**:
- What subset of Python does this evaluate? Is it documented?
- Error messages: are they helpful? Do they include the expression and position?
- `py_date.js` (574 lines): is this a complete Python `datetime` implementation? Edge cases?
- Security: can arbitrary Python be injected? (Domain filters come from server — what's the trust model?)
- `py_interpreter.js` (507 lines): is the execution model correct for Odoo's domain expressions?
- Performance: is parsing cached? Domains are re-evaluated frequently.

**Status**: `[X]` — Audited + 5 fixes applied 2026-03-07.

**Top findings (implemented)**:
1. **[CRITICAL] py_interpreter.js:applyBinaryOp** — `is` and `is not` operators were tokenized and parsed correctly (bp=60) but had no case in the switch → always threw `EvaluationError` at runtime; mapped to JS `===` / `!==` respectively
2. **[HIGH] py_interpreter.js:pytypeIndex** — `boolean` type had no case, fell through to `throw`; Python booleans sort with numbers (True=1, False=0) → added `case "boolean": return 2`
3. **[HIGH] py_parser.js:`**` associativity** — `2**3**2` parsed left-associatively (= 64) instead of right-associatively (= 512); Python standard requires right → use `bindingPower(current) - 1` as right operand's minimum binding power
4. **[HIGH] py_date_helpers.js:tmxxx** — `hour ||= 0` / `minute ||= 0` etc. used `||=` which treats `0` as falsy, replacing valid midnight `hour=0` with `0` correctly but by accident — explicit `0` args would be silently discarded if already `0` was passed by logic → replaced with `??=` (only defaults `null`/`undefined`)
5. **[HIGH] py.js** — every `evaluateExpr()` call re-tokenized and re-parsed the expression string; in typical Odoo views with 50+ fields × N records, this is O(fields×records) redundant work → added 500-entry LRU-style `Map` parse cache; evicts oldest entry (Map insertion order) when full

**Remaining findings (deferred)**:
- `py_date.js:574` — `PyDate`, `PyDateTime`, `PyTime` each re-implement `strftime`/`strptime` with partial format code coverage; missing `%j`, `%U`, `%W`, `%Z`, `%z` (TYPE/high)
- `py_interpreter.js:allowedFns` — allowlist is a `Set` of function references; any function added via `patch()` to BUILTINS after module load is silently rejected (BUG/medium — extensibility)
- `py_tokenizer.js:tokenize` — no position tracking; error messages show only the token value, not line/column (ERR/medium)
- `py_builtin.js` — `context_today()` delegates to `new Date()` (browser local time); should use server timezone from `localization` (BUG/medium)
- `py_date.js:PyTimeDelta.divide` — integer division `//` returns `PyTimeDelta` but `int // timedelta` raises `TypeError` in Python; asymmetry not enforced (TYPE/low)
- `py_utils.js:formatAST` — covers only 12 of 15 AST node types; `ASTLookup`, `ASTIf`, `ASTObjLookup` missing → falls back to `"?"` (DEAD/low)

### Group 06 — Domain / Tree / Context

**Files**:
```
core/constants.js
core/context.js
core/domain.js                                      (490 lines)
core/tree/condition_tree.js                          (351 lines)
core/tree/virtual_operators.js                       (428 lines)
core/tree/construct_tree_from_expression.js          (275 lines)
```

**Key questions for the agent**:
- `domain.js` (490 lines): what is the full Domain API? Is the class too large?
- Relationship between `domain.js` and `core/tree/`? Does Domain delegate to tree or duplicate logic?
- `virtual_operators.js` (428 lines): what are "virtual operators"? UI-level or data-level?
- `condition_tree.js`: is this the data structure for domain trees? Is it typed?
- `context.js`: what is a "context" in Odoo? How does it merge? Are there known conflict issues?

**Status**: `[X]` — Audited + 1 fix applied 2026-03-07.

**Top findings (implemented)**:
1. **[MEDIUM] domain.js:108-113** — `removeDomainLeaves` inner `processLeaf` accesses `elements[idx + 1].type` and `elements[idx + 2].type` without bounds checking; malformed or partially-consumed domain lists throw `TypeError: Cannot read properties of undefined (reading 'type')` → added `?.` optional chaining throughout

**Remaining findings (deferred)**:
- `domain.js:435-440` — `matchCondition` returns `true` for `any`, `not any`, `child_of`, `parent_of` operators (cannot be evaluated client-side); this is a deliberate approximation (false positives > false negatives for display filters) but callers using `domain.contains()` for correctness will get wrong results — needs `canContain()` predicate or `InvalidDomainError` for `child_of`/`parent_of` (BUG/high — by design)
- `context.js:33` — `makeContext` skips `""` but not `null`/`undefined`; `Object.assign(context, null)` is a no-op but silently swallows bad input → add truthiness guard (BUG/low)
- `tree/virtual_operators.js:381` — `introduceVirtualOperators` makes 5 sequential full-tree traversals; single-pass combining would reduce to O(n) per transformation (PERF/medium)
- `context.js:51` — `getPartialNames` returns `[]` for function-call AST (type 8); causes premature evaluation of contexts with function calls even when names are unavailable (DEAD/medium)
- `tree/virtual_operators.js:185` — duplicate right-bound `'today +1d'` in `BOUNDS_SMART_DATES` causes ambiguity between `'today'` and `'month to date'` ranges (BUG/low)

### Group 07 — Network & RPC

**Files**:
```
core/browser/feature_detection.js
core/browser/cookie.js
core/browser/anchor_scroll.js
core/browser/router.js                     (435 lines)
core/network/content_disposition.js        (248 lines)
core/network/rpc.js                        (218 lines)
core/network/rpc_cache.js                  (322 lines)
core/network/rpc_dedup.js
core/network/download.js                   (345 lines)
core/assets.js                             (306 lines)
```

**Key questions for the agent**:
- `rpc.js`: error handling — what happens on network timeout? On 500? On CSRF failure?
- `rpc_cache.js` (322 lines): what is the cache invalidation strategy? Are there memory leak risks?
- `rpc_dedup.js`: deduplication by what key? Race condition handling?
- `router.js` (435 lines): does it handle browser history correctly? `popstate` edge cases?
- `download.js` (345 lines): memory management — are blob URLs revoked after use?
- `assets.js` (306 lines): dynamic script loading — error handling if asset fails to load?

**Status**: `[X]` — Audited + 3 fixes applied 2026-03-07.

**Top findings (implemented)**:
1. **[HIGH] core/network/rpc.js:157** — No XHR `timeout` configured anywhere; a server that accepts TCP connection but never sends bytes leaves the XHR permanently pending, freezing all UI waiting on the RPC → added `request.timeout = 120000` (2 min, matches server-side RPC timeout) and `"timeout"` event handler for caller-owned XHR only (`!settings.xhr` guard)
2. **[MEDIUM] core/browser/router.js:350** — `pushState({}, "", url.href)` uses empty state object for hash-fragment navigation; Back button re-parses the URL inefficiently instead of restoring `nextState` snapshot → replaced `{}` with `{ nextState: state }` (state already computed at line 348)
3. **[LOW] core/browser/cookie.js:33** — `return value || ""` loses falsy cookie values like `"0"` or `"false"` → replaced with `value ?? ""`

**Remaining findings (deferred)**:
- `rpc.js:158-174` — only HTTP 502 is specially handled; 401 (session expired), 403 (CSRF failure), 503/504 all fall into the JSON-parse path → conflate network loss with auth/server errors (ERR/high)
- `rpc.js:207` — abort race: XHR `load` can fire after `.abort()` if browser received full response before abort processed → double `RPC:RESPONSE` event on rpcBus (ERR/medium)
- `rpc_cache.js:31` — `MAX_STORAGE_SIZE` is 2 GiB absolute; `navigator.storage.estimate()` measures total browser storage (all origins) — user with heavy apps triggers Odoo's DB deletion even when Odoo itself uses minimal space (PERF/medium)
- `rpc_cache.js:17` — `jsonEqual` serializes full RPC responses to strings for change detection; O(n) allocations on every settled "always" request (PERF/medium)
- `rpc_dedup.js:42` — dedup key uses `JSON.stringify(params)` without key sorting; semantically identical params with different insertion order are not deduplicated (BUG/low)
- `download.js:145` — blob URL revoked after 250ms; too short on slow systems, download may begin after URL is revoked (BUG/medium)
- `browser/feature_detection.js:16` — `isBrowserChrome()` returns `true` for Edge (Chromium-based) — Chrome-specific code paths incorrectly activate for Edge users (BUG/medium)

### Group 08 — Registry, Patch & Templates

**Files**:
```
core/utils/patch.js
core/registry.js                       (287 lines)
core/templates.js                      (255 lines)
core/template_inheritance.js           (415 lines)
```

**Key questions for the agent**:
- `patch.js`: is there a way to un-patch? (For tests). Are patches stacked correctly?
- `registry.js`: `getAll()` returns a `.slice()` copy — is this intentional? Performance implications?
- `template_inheritance.js` (415 lines): how does OWL template XPath inheritance work? Is this the right layer?
- Are there circular dependency risks between registry → services → registry?

**Status**: `[X]` — Audited + 4 fixes applied 2026-03-07.

**Top findings (implemented)**:
1. **[CRITICAL] template_inheritance.js:14** — `getTranslationContext()` recursion has no base case for null/detached nodes; crashes with `TypeError` on `el.hasAttribute` when called from `replace()` (line 309) or `getNodes()` (line 212) on cloned elements → added `if (!el || !el.hasAttribute) return ""` guard
2. **[HIGH] template_inheritance.js:248** — `modifyAttributes()` casts Text node to Element and accesses `.outerHTML` (undefined on Text); error message was always "Useless element content undefined" → fixed to use `.nodeValue`
3. **[HIGH] template_inheritance.js:312** — `loc.firstChild.replaceWith()` called without null check; XPath snapshot items may be leaf elements whose text node was already consumed → added `if (loc.firstChild)` guard
4. **[MEDIUM] templates.js:205** — `templateExtensions[inheritFrom] ||= []` creates a sparse array indexed by numeric `blockId`; intent is a sparse record (map) → changed to `Object.create(null)` to eliminate prototype-method pollution in `for...in` iteration

**Remaining findings (deferred)**:
- `template_inheritance.js:153` — `new Document()` created per XPath operation during module load; shared reusable instance would eliminate all these allocations (PERF/medium)
- `templates.js` — all template state in module-level mutable singletons (`templates`, `parsedTemplates`, etc.); no clean reset between tests → cross-test pollution (STRUCT/high)
- `templates.js:180` — `unregisterTemplate()` fails to clear `parsedTemplateExtensions[name]` cached from other templates that referenced it → stale cache entries (BUG/medium)
- `registry.js:173` — `getAll()` / `getEntries()` return `.slice()` on every call for mutation safety; callers that only read could use an internal non-sliced version (PERF/low)

### Group 09 — Errors, Position & Colors

**Files**:
```
core/colors/colors.js                    (222 lines)
core/errors/error_utils.js               (210 lines)
core/errors/uncaught_errors.js
core/position/utils.js                   (364 lines)
core/position/position_hook.js
```

**Key questions for the agent**:
- `colors.js` in `core/colors/` AND `colors.js` in `core/utils/format/` — are these two separate things? If so, why? If not, why are there two files?
- `position/utils.js` (364 lines): this is large for "utilities". What positioning algorithms are used? Viewport edge detection?
- `uncaught_errors.js`: does it properly clean up event listeners? Infinite loop risk if error handler throws?

**Status**: `[X]` — Audited + 3 fixes applied 2026-03-07.

**Top findings (implemented)**:
1. **[MEDIUM] services/error_service.js:112** — `new URL(filename)` throws `TypeError` for empty filename (`""`); happens for inline `<script>` tags with a `lineno` (which bypasses the `isRedactedError` guard); error inside error handler creates a new unhandledrejection → added `!!filename &&` short-circuit guard
2. **[MEDIUM] core/position/position_hook.js:61** — `options.position = ...` mutated the caller's options object on every reposition (sticky position intent); if the same options object is passed to multiple `usePosition` hooks or is a reactive OWL proxy, this causes state leakage / spurious re-renders → extracted to `let lastPosition` local variable
3. **[PERF] core/position/utils.js:324** — `matches.sort()` used to find minimum-malus entry; O(n log n) with GC-pressure sort allocation on every scroll event when popper is near a viewport edge → replaced with O(n) linear minimum scan

**Remaining findings (deferred)**:
- `core/colors/colors.js` vs `core/utils/format/colors.js` — two files named `colors.js` serving different purposes (palette utilities vs CSS color space conversions); correct split but confusing naming → consider renaming `core/colors/colors.js` to `palette.js` (NAME/low)
- `core/errors/error_utils.js:176` — `error.stack` mutated in-place for Firefox compat; benign in practice (annotateTraceback is called once per error) but fragile under repeated annotation (PAT/low)
- `core/errors/error_utils.js:93-94` — rethrow in `fullAnnotatedTraceback` propagates as new unhandledrejection; must be caught by error service's handler or double-dialog occurs (ERR/medium — requires error_service.js audit)
- `core/position/utils.js:84` — `getIFrame()` spreads live HTMLCollection into array on every `computePosition()` call (every scroll event when target is in iframe) → cache per (popper, target) pair (PERF/medium)

---

## Phase 2: model/ — Data Layer

**Constraint**: No OWL components, no views, no search. Pure data manipulation and ORM communication.

### Group 10a — Relational Model: Core

**Files**:
```
model/types.js                                          (65 lines)
model/model.js                                          (290 lines)
model/record.js                                         (268 lines)
model/relational_model/errors.js                        (37 lines)
model/relational_model/datapoint.js                     (64 lines)
model/relational_model/relational_model.js              (934 lines)
```

**Key questions**:
- `model/model.js` vs `model/relational_model/relational_model.js`: what's the split? Is `model.js` a base class?
- `model/record.js` vs `model/relational_model/record.js` (1043 lines): two record files — why? What does each own?
- `relational_model.js` (934 lines): god file candidate — can it be split?
- `datapoint.js`: what is a "datapoint"? Base class for Record and List?

**Implemented fixes**:
- [X] `relational_model.js:271` — `config.groupBy = null` → `config.groupBy = []` (groupBy must always be array)
- [X] `relational_model.js:512` — `config.offset = 0` mutates shared config ref → `{ ...config, offset: 0 }` spread copy
- [X] `relational_model.js:654` — O(n²) JSON serialization in group comparison → pre-build `Set<string>` before forEach
- [X] `commands.js:21,27` — `delete values.id` mutates caller's object → destructure `{ id: _id, ...rest }`
- [X] `command_builder.js:76` — `getRecord()` can return undefined → `else if (record)` guard before `getRecordChanges`
- [X] `group.js:88-94` — `applyFilter` with truthy filter didn't update `this.count` after load → moved count update out of else branch
- [X] `field_values.js:55` — `field.selection.find()` crashes if `field.selection` not array → `Array.isArray` guard
- [X] `field_values.js:153` — `info.value.plus(granularityToInterval[undefined])` crashes for ungranularized date groupBy → `const interval = ...; if (interval) { ... }`
- [X] `field_metadata.js:57` — mutates static `fieldDependencies` class property array → `const field = "readonly" in rawField ? rawField : { ...rawField, readonly: true }`
- [X] `resequence.js:36` — `fromIndex=-1` causes `splice(-1,...)` silently removing last record → throw Error
- [X] `resequence.js:92` — `Math.min(...[undefined,...])` = NaN → `|| 0` masks to 0, resetting all sequences → filter nulls, check length

**Deferred** (additional):
- `field_context.js:15-19` eager default param eval — requires invasive signature change; only crashes for non-existent activeFields (programming error)
- `group.js:38-46` `config.record.context` mutation — lower risk (config objects are not reused across groups in practice)

**Status**: `[X]`

### Group 10b — Relational Model: Lists

**Files**:
```
model/relational_model/static_list_utils.js          (149 lines)
model/relational_model/static_list_sort.js           (136 lines)
model/relational_model/static_list_command_engine.js (275 lines)
model/relational_model/static_list.js                (868 lines)
model/relational_model/dynamic_record_list.js        (202 lines)
model/relational_model/dynamic_group_list.js         (428 lines)
model/relational_model/dynamic_list.js               (585 lines)
```

**Key questions**:
- `static_list.js` (868 lines) vs `dynamic_list.js` (585 lines): core difference between static and dynamic? Is the split clean?
- `static_list_command_engine.js` (275 lines): what are "commands"? CQRS-style mutations?
- `dynamic_group_list.js` (428 lines): group-by results — does it handle nested groups?
- Overlap between `static_list_utils.js` and `static_list_sort.js` — why two utility files?

**Implemented fixes**:
- [X] `static_list.js:708` — `slice(offset, limit)` off-by-one → `slice(offset, offset + limit)` in `_discard()`
- [X] `static_list.js:723` — `records[targetIndex - 1].data` crashes when `targetIndex=0` → optional chain with `?? 0`
- [X] `static_list_sort.js:108` — `Object.entries(toReorder)` on array → `toReorder.entries()` (numeric keys, no Number() cast)
- [X] `static_list_utils.js:118` — `[...copyFields, "display_name"].includes(name)` in loop → pre-built `Set` (`skipFields.has()`)

**Deferred** (no clear bug):
- `dynamic_group_list.js:68` `get records()` flat allocation — deferred (OWL reactivity risks with naive caching)

**Status**: `[X]`

### Group 10c — Relational Model: Record Internals

**Files**:
```
model/relational_model/record_utils.js              (151 lines)
model/relational_model/record_preprocessors.js      (231 lines)
model/relational_model/record_value_transforms.js   (181 lines)
model/relational_model/record_validator.js          (98 lines)
model/relational_model/record_save.js               (192 lines)
model/relational_model/record.js                    (1043 lines — LARGEST in model/)
```

**Implemented fixes**:
- [X] `record_preprocessors.js:206` — `return` → `continue` in properties for...of loop (HIGH — dropped all subsequent field changes silently)
- [X] `record_value_transforms.js:48` — `properties` case: `value.map()` crashes on null/false → `if (!value) return false` guard

**Deferred**:
- `record.js:989` parallel preprocessors mutate shared `changes` — concurrent writes are safe because async preprocessors operate on distinct field keys (m2o, reference, m2o_reference are type-exclusive per field); no actual race
- `record_validator.js:52` html Markup `.length` check — fragile but works with current OWL Markup API
- `record_save.js:174` x2many StaticList in _values on reload=false — intentional design (StaticList cleared via `_clearCommands()`)

**Status**: `[X]`

### Group 10d — Relational Model: Supporting

**Files**:
```
model/relational_model/commands.js               (55 lines)
model/relational_model/operation.js              (33 lines)
model/relational_model/utils.js                  (32 lines)
model/relational_model/group.js                  (151 lines)
model/relational_model/field_spec.js             (119 lines)
model/relational_model/field_context.js          (87 lines)
model/relational_model/field_metadata.js         (317 lines)
model/relational_model/field_values.js           (326 lines)
model/relational_model/command_builder.js        (170 lines)
model/relational_model/onchange_coalescer.js     (104 lines)
model/relational_model/resequence.js             (104 lines)
```

**Implemented fixes**:
- [X] `field_values.js:175` — inverted `sum_currency` condition: `currencies.length === 1` → `!currencies || currencies.length !== 1`
- [X] `field_values.js:320` — `reference` case in `fromUnityToServerValues` was TODO-commented out → implemented `resModel,resId` format
- [X] `onchange_coalescer.js:93` — `evaluateFn` failure left all queued promises hanging forever → `[resolve, reject]` pairs + try/catch + reject-all
- [X] `field_metadata.js:140` — `combineModifiers` AND: `!mod1` treated `""` as "False" → explicit `=== "False"` check
- [X] `record_validator.js:61` — non-required x2many with invalid children flagged parent as required field → wrapped both conditions under `isRequired(fieldName)`
- [X] `record_preprocessors.js:206` — stale relatedPropertyField key left in `changes` after `continue` → `delete changes[fieldName]` before `continue`

**Deferred**:
- `resequence.js:38` `!== null` vs `!== undefined` — produces correct `toIndex=0` coincidentally; fixed in 10a/10b section
- `field_context.js:72` nextId overflow — theoretical, practically unreachable

**Status**: `[X]`

### Group 10e — Sample Data

**Files**:
```
model/sample_field_generators.js    (191 lines)
model/sample_data.js                (105 lines)
model/sample_server.js              (761 lines)
```

**Findings** (all deferred — sample/test infra only, not production path):
- `sample_server.js:604` `params.groupBy[0]` — crashes if groupby omitted, but web_read_group always provides groupby
- `sample_server.js:492` progress bar boolean/string keys — agent analysis was incorrect; code is correct (conversion happens before key init)
- `sample_field_generators.js:40` non-uniform date distribution (triangular via `random - random`) — cosmetic only
- `sample_server.js:430` JSON.stringify grouping key O(n) per record — acceptable at 16-record sample sizes

**Status**: `[X]`

---

## Phase 3: fields/ — Feature Layer

**Constraint**: fields/ cannot import from views/ or search/ (enforced by ESLint).

### Group 11 — Fields: Core System

**Files**:
```
fields/standard_field_props.js
fields/field_types.js
fields/field_tooltip.js
fields/field_utils.js
fields/field_widths.js
fields/hooks/record_observer.js
fields/numpad_decimal_hook.js
fields/file_handler.js
fields/translation_button.js
fields/translation_dialog.js
fields/dynamic_placeholder_hook.js
fields/dynamic_placeholder_popover.js
fields/input_field_hook.js
fields/parsers.js
fields/formatters.js
fields/field.js
```

**Key questions**:
- `field.js`: is this the base OWL component for all fields? What does the subclass contract look like?
- `formatters.js` vs `parsers.js`: are all field types covered? Are there format/parse round-trip tests?
- `input_field_hook.js`: what pattern does this establish for input handling?
- `translation_dialog.js` + `translation_button.js`: how do inline translations work?

**Findings**:
- `translation_dialog.js:43-44` + `translation_dialog.xml:12,16,22` **FIXED** — Template read `props.isText`/`props.showSource` but JS wrote to `this.isText`/`this.showSource` (plain properties); text fields always rendered `<input>` never `<textarea>`. Moved to `useState`, updated template to `state.isText`/`state.showSource`
- `translation_dialog.js:50` **FIXED** — `relatedLanguage[1]` crash when language not found: `relatedLanguage?.[1] ?? term.lang`
- `translation_dialog.js:114-115` **FIXED** — `close()` not called if `onSave()` throws: wrapped in try/finally
- `field.js:518-524` **FIXED** — `fieldInfo.placeholder = ...` mutated `this.props.fieldInfo` when attrs not provided (only the attrs branch made a copy): added `else { fieldInfo = { ...fieldInfo }; }` to always copy before mutation
- `file_handler.js:97` **FIXED** — `allowedMIMETypes.includes(file.type)` was substring match on comma-separated string; changed to `.split(",").map(t=>t.trim()).includes(file.type)`
- `input_field_hook.js:168` **FIXED** — `isDirty = false` cleared before parse attempt; if parse throws with `urgent=true`, dirty flag lost permanently. Moved clear to after successful parse
- `dynamic_placeholder_popover.js:54-61` **FIXED** — `isTemplateEditor`/`allowedQwebExpressions` set as non-reactive instance properties; moved to `useState` with defaults; also fixed `fieldName` non-reactive assignment
- `dynamic_placeholder_hook.js:36` **FIXED** — `replace("|||", "")` → `replaceAll("|||", "")`
- `formatters.js:284` — `encodeURIComponent` used for HTML escaping in `formatMany2one` escape option; no callers found using `escape: true` so deferred
- `file_handler.js:49` **FIXED** (round 2) — `return` in batch upload loop aborted entire batch on oversized file; changed to `continue` to skip only that file
- `translation_button.js:63` **FIXED** (round 2) — `new Intl.Locale(user.lang)` throws RangeError when lang is empty string; added `|| "en"` fallback
- `input_field_hook.js:87-92` **FIXED** (round 2) — `pendingUpdate = true` not reset when `record.update()` rejects; wrapped with try/finally
- `parsers.js:73` **FIXED** (round 2) — `options.thousandsSep.match()` crashes if thousandsSep is undefined; changed to optional chaining `?.match()`
- `formatters.js:297` **FIXED** (round 2) — `formatX2many(false)` crashes on `false.currentIds`; added falsy guard returning "No records"

**Status**: `[X]`

### Group 12 — Fields: Basic & Selection

**Files**: `fields/basic/**` (24 files) + `fields/selection/**` (10 files) + `fields/display/**` (7 files, excluding statusbar/gauge → Group 15)

**Key questions**:
- Pattern consistency: do all basic fields follow the same `static props` + `static supportedTypes` + `static displayName` pattern?
- Are `text_input_field_base.js` and `numeric_input_field_base.js` used correctly by subclasses?
- `selection_like_field.js`: shared base for all selection variants?
- `monetary_field.js`: currency symbol placement — does it handle RTL?

**Findings**:
- `progress_bar_field.js:54,61` **FIXED** — `shouldSave: () => this.props.readonly` inverted: saved on readonly, skipped autosave in edit mode. Fixed to `() => !this.props.readonly`
- `float_time_field.js:61` **FIXED** — `options.displaySeconds` (camelCase) read instead of `options.display_seconds` (snake_case from XML); feature silently broken for all users
- `boolean_icon_field.js:22` **FIXED** — `update()` had no readonly guard; field always clickable/writable even in readonly mode. Added `if (this.props.readonly) return;` and `readonly: dynamicInfo.readonly` in extractProps
- `float_toggle_field.js:31` **FIXED** — `indexOf` with `===` for float comparison; server round-trip can change bit representation. Changed to `findIndex((v) => Math.abs(v - stored) < 1e-9)`
- `float_field.js:43-48` **FIXED** — `return this.value` returned `false` (ORM unset sentinel) as display value; changed to `return this.value === false ? "" : this.value`
- `float_factor_field.js:29` **FIXED** — `false * factor = 0` silently converted unset fields to zero. Added `raw === false ? false : raw * factor` guard; also fixed `extractProps` mutation via spread
- `badge_selection_field.js:21` **FIXED** — `default: "md"` inside prop schema silently ignored by OWL (defaults go in `static defaultProps`); moved to `static defaultProps = { size: "md" }`
- `json_checkboxes_field.js:14` — template `"account.JsonCheckboxes"` cross-module dependency: deferred (requires template refactor + account module coordination)
- `badge_selection_field_with_filter.js:15` — required `allowedSelectionField` prop can receive undefined: deferred (needs design decision)
- `state_selection_field.js:95` — duplicate `displayName: _t("Label Selection")` collision: deferred (low-risk UI concern)
- `monetary_field.js:83` **FIXED** (round 2) — `getCurrency(this.currencyId).digits` double-called getCurrency (once via `this.currency` guard, once directly); replaced with `this.currency?.digits ?? null`
- `selection_field.js:56` **FIXED** (round 2) — `options.find()` returns undefined for stale many2one value; `option[0]` TypeError; added `if (!option) return` guard
- `badge_selection_field.js:45` **FIXED** (round 2) — same find() undefined crash as selection_field; added `if (!option) return` guard
- `badge_selection_field_with_filter.js:22` **FIXED** (round 2) — `allowedSelection.includes()` crashes when field is null/false on new records; changed to `allowedSelection?.includes(value) ?? false`
- `state_selection_field.js:65` **FIXED** (round 2) — `this.options[0][0]` throws when selection array is empty; changed to `this.options[0]?.[0]`
- `json_checkboxes_field.js:22` **FIXED** (round 2) — `useState(null)` when JSON field is empty/false crashes OWL; added `?? {}` fallback on both useState and Object.assign

**Status**: `[X]`

### Group 13 — Fields: Relational

**Files**:
```
fields/relational/relational_active_actions.js
fields/relational/special_data.js
fields/relational/many2one_barcode/many2one_barcode_field.js
fields/relational/many2one_reference_integer/many2one_reference_integer_field.js
fields/relational/many2many_checkboxes/many2many_checkboxes_field.js
fields/relational/many2many_tags_avatar/many2many_tags_avatar_field.js
fields/relational/many2many_tags/kanban_many2many_tags_field.js
fields/relational/many2one_avatar/kanban_many2one_avatar_field.js
fields/relational/many2one_avatar/many2one_avatar_field.js
fields/relational/many2many_binary/many2many_binary_field.js
fields/relational/many2one_reference/many2one_reference_field.js
fields/relational/many2one/many2one_field.js
fields/relational/reference/reference_field.js
fields/relational/x2many_crud.js
fields/relational/many2many_tags/many2many_tags_field.js
fields/relational/many2one/many2one.js
fields/relational/x2many_dialog.js
fields/relational/x2many/list_x2many_field.js
fields/relational/x2many/x2many_field.js
fields/relational/many2x_autocomplete.js
```

**Key questions**:
- `many2x_autocomplete.js` (630 lines): this is shared by many2one and many2many — is the abstraction clean?
- `many2one.js` (408 lines) vs `many2one_field.js` (144 lines): why two files for many2one?
- `x2many_crud.js`: what CRUD operations does this handle? Create vs write vs unlink?
- Are RPC calls in fields properly cancellable when the field unmounts?

**Findings**:
- `many2one_field.js:81` **FIXED** — `extractM2OFieldProps(staticInfo, dynamicInfo = {})` default param: reference_field called with one arg → `dynamicInfo.context` TypeError on every reference field render
- `kanban_many2many_tags_field.js:15` **FIXED** — `delete tag.onClick` mutated original object; replaced with destructuring spread
- `x2many_dialog.js:341` — Stale `record` closure in Save & New: deferred (couldn't confirm in code review)

**Status**: `[X]`

### Group 14 — Fields: Specialized

**Files**:
```
fields/specialized/ace/ace_field.js
fields/specialized/color_picker/color_picker_field.js
fields/specialized/kanban_color_picker/kanban_color_picker_field.js
fields/specialized/google_slide_viewer/google_slide_viewer.js
fields/specialized/iframe_wrapper/iframe_wrapper_field.js
fields/specialized/ir_ui_view_ace/ace_field.js
fields/specialized/field_selector/field_selector_field.js
fields/specialized/journal_dashboard_graph/journal_dashboard_graph_field.js
fields/specialized/user_groups/res_user_group_ids_popover.js
fields/specialized/user_groups/res_user_group_ids_privilege_field.js
fields/specialized/user_groups/res_user_group_ids_field.js
fields/specialized/domain/domain_field.js
fields/specialized/properties/calendar_properties_field.js
fields/specialized/properties/card_properties_field.js
fields/specialized/properties/property_text.js
fields/specialized/properties/property_tags.js
fields/specialized/properties/property_definition_selection.js
fields/specialized/properties/property_value.js
fields/specialized/properties/property_definition.js
fields/specialized/properties/properties_field.js  (1098 lines — GOD FILE)
```

**Key questions**:
- `properties_field.js` at 1098 lines: this MUST be split. Map every method and identify extraction points.
- Two `ace_field.js` files — does `ir_ui_view_ace/` duplicate or extend `ace/`?
- `domain_field.js`: does it properly integrate with `core/domain.js`?
- XSS risks in `iframe_wrapper_field.js` and `google_slide_viewer.js`?

**Findings**:
- `properties_field.js:1051` **FIXED** — `this.props.value = propertiesValues` direct OWL prop mutation removed (record.update already handles state synchronously)
- `res_user_group_ids_popover.js:67` **FIXED** — `this.privileges[group.privilege_id].name` → optional chaining guard
- `journal_dashboard_graph_field.js:25` **FIXED** — `this.data` parsed once in setup (stale on record change); moved into useEffect so it re-reads on each render
- `res_user_group_ids_field.js:40` **FIXED** — broken sort comparator `(privilege) => privilege.sequence` → `(a, b) => a.sequence - b.sequence`
- `property_tags.js:222` **FIXED** — `replace(" ", "_")` → `replaceAll(" ", "_")` (only first space was replaced)
- `property_definition.js` — `oldDefinition.model` reported bug: file has 500 lines, pattern not found; bug not present in current version

**Status**: `[X]`

### Group 15 — Fields: Display, Temporal & Media

**Files**:
```
fields/display/gauge/gauge_field.js
fields/display/statusbar/statusbar_field.js
fields/temporal/remaining_days/remaining_days_field.js
fields/temporal/timezone_mismatch/timezone_mismatch_field.js
fields/temporal/datetime/list_datetime_field.js
fields/temporal/datetime/datetime_field.js
fields/media/attachment_image/attachment_image_field.js
fields/media/contact_image/contact_image_field.js
fields/media/image_url/image_url_field.js
fields/media/pdf_viewer/pdf_viewer_field.js
fields/media/signature/signature_field.js
fields/media/binary/binary_field.js
fields/media/image/image_field.js
```

**Key questions**:
- `datetime_field.js`: timezone handling bugs? Off-by-one in date ranges?
- `statusbar_field.js`: correctly handles state transitions? Missing states?
- `image_field.js`: binary upload — XSS risks? File size validation?
- `binary_field.js`: download URL construction — injection risks?

**Findings**:
- `image_field.js:163-178` **FIXED** — Safari WebP silent fallback: check `dataUrl.startsWith("data:image/webp")` before setting type; added `getContext("2d")` null guard; added `error` event listener to image load promises
- `image_field.js:195` **FIXED** — Resize loop ctx null check with `continue`
- `signature_field.js:144` **FIXED** — `signatureImage.split(",")[1]` → `signatureImage?.split(",")[1]` (null-safe)
- `timezone_mismatch_field.js:63-68` **FIXED** — `offset` could be null if regex fails → added early `return option` guard
- `pdf_viewer_field.js` **FIXED** — `URL.createObjectURL()` blob never revoked: added revokeObjectURL in onFileUploaded, onWillUpdateProps, and onWillDestroy
- `binary_field.js:42` **FIXED** — `toBase64Length(MAX_FILENAME_SIZE_BYTES)` wrong for text filename truncation → changed to direct `MAX_FILENAME_SIZE_BYTES` (255 chars)

**Status**: `[X]`

---

## Phase 4: search/ — Search Infrastructure

### Group 16a — Search: Model & Logic

**Files**:
```
search/search_context.js                (69 lines)
search/search_state.js                  (150 lines)
search/search_facets.js                 (150 lines)
search/search_domain.js                 (282 lines)
search/search_split_domain.js           (142 lines)
search/search_enrichment.js             (72 lines)
search/search_group_by.js               (185 lines)
search/search_favorites.js              (181 lines)
search/search_properties.js             (214 lines)
search/with_search/with_search.js       (111 lines)
search/search_arch_parser.js            (520 lines)
search/search_query_mutations.js        (378 lines)
search/search_model.js                  (1046 lines — GOD FILE)
```

**Key questions**:
- `search_model.js` (1046 lines): core search state machine. Map all methods. What can be extracted into the already-split files?
- `search_arch_parser.js` (520 lines): parsing `<search>` XML views — is it complete? Missing field types?
- The many `search_*.js` files — were these split FROM `search_model.js`? Or did they always exist? Is the boundary clear?
- `search_query_mutations.js` (378 lines): this name suggests pure mutation functions — is it actually pure?
- `search_split_domain.js`: what does "split" mean here? Domain splitting for compound conditions?

**Findings**:
- `search_model.js:244` **FIXED** — `Promise.all(labels.map(...))` crashed entire search model load when any many2one record was deleted. Changed to `Promise.allSettled` with per-result warning logging.
- `search_state.js:137` **FIXED** — `if (defaultValue)` skipped falsy but valid search defaults (`0`, `false`, `""`). `search_default_active = 0` (show archived) silently had no effect. Changed to `if (defaultValue != null)`.
- `search_split_domain.js:84+131` **FIXED** — `queryItemIndex` was captured before the group-by reorder (`createNewGroupBys` block at lines 107-119 prepends group-bys, shifting the favorite's position forward). Added `queryItemIndex += activeItemGroupBys.length` after the reorder to keep the insertion point accurate before `deactivateGroup`.
- `search_arch_parser.js:49` **FIXED** — `getContextGroupBy` called `.split(":")` on `group_by` which throws if `group_by` is already an array (multi-group-by context). Added Array.isArray check; uses first element in array case.
- `search_query_mutations.js:148` **FIXED** — `createNewFilters` mutated caller's `preFilter` objects via `Object.assign(preFilter, {...})`; any code holding references to originals saw corrupted data. Changed to `Object.assign({}, preFilter, {...})`. Also added missing return of created IDs array.
- `search_favorites.js:23` **FIXED** — `evaluateExpr(irFilter.context, user.context)` with no try/catch; a corrupted stored filter context crashed the entire search model load for all users. Wrapped in try/catch with `context = {}` fallback and warning log.

**Status**: `[X]`

### Group 16b — Search: UI

**Files**:
```
search/pager_hook.js                                    (39 lines)
search/layout.js                                        (45 lines)
search/breadcrumbs/breadcrumbs.js                      (28 lines)
search/utils/misc.js                                    (32 lines)
search/utils/group_by.js                               (62 lines)
search/utils/dates.js                                  (390 lines)
search/custom_group_by_item/custom_group_by_item.js    (31 lines)
search/custom_favorite_item/custom_favorite_item.js    (101 lines)
search/cog_menu/cog_menu.js                            (99 lines)
search/properties_group_by_item/                        (88 lines)
search/action_menus/action_menus.js                    (208 lines)
search/search_bar_menu/search_bar_menu.js              (196 lines)
search/search_panel/search_panel_fetch.js              (109 lines)
search/search_panel/search_panel_state.js              (295 lines)
search/search_panel/search_panel.js                    (489 lines)
search/search_bar/search_bar_toggler.js                (64 lines)
search/search_bar/search_bar.js                        (779 lines)
search/control_panel/control_panel.js                  (805 lines)
```

**Key questions**:
- `control_panel.js` (805 lines): main search UI coordinator — what does it own vs delegate?
- `search_bar.js` (779 lines): the input field and suggestions — should be split?
- `search_panel.js` (489 lines): the left-sidebar filter panel — why 489 lines?
- `search/utils/dates.js` (390 lines): date utilities specific to search — does this overlap with `core/l10n/dates.js`?
- `action_menus.js` (208 lines): the "Action" dropdown in list/form — is it correctly in search/?

**Findings**:
- `dates.js:154-158` **FIXED** — `constructDateRange` mutated caller's `setParam` in place; when called via `getSetParam()` returning the QUARTER_OPTIONS constant's `setParam` by reference, `delete setParam.quarter` permanently corrupted the module-level constant for the entire session. Cloned with `{ ...params.setParam }` and rewrote the quarter branch.
- `search_bar_menu.js:159` **FIXED** — `sharedFavorites.length = 3` truncated the live array returned by `getSearchItems` in place; if this is a direct reference to the model's internal collection, it permanently deletes items. Changed to `return sharedFavorites.slice(0, 3)`.
- `search_panel.js:416` **FIXED** — `document.querySelectorAll(".o_search_panel_filter_group")` was a global DOM query, corrupting checkbox state of all search panels on the page (dialogs, embedded views). Scoped to `this.root.el.querySelectorAll(...)`.
- `control_panel.js:773` **FIXED** — `document.querySelector(".o-control-panel-adaptive-dropdown...")` global query; would match first panel found in document. Scoped to `this.root.el.querySelector(...)`.
- `search_panel_fetch.js:29` **FIXED** — `value[parentField] || false` treated parentId `0` as "no parent"; changed to `?? false` (nullish coalescing); also fixed `if (parentId && ...)` → `if (parentId !== false && ...)` and `if (!parentId)` → `if (parentId === false)` for consistency.
- `cog_menu.js:47` **FIXED** — `this.registryItems` uninitialized before `onWillStart` resolves; `cogItems` getter spreads it → TypeError. Added `this.registryItems = []` before hooks.
- `search_panel_state.js:166,220` **FIXED** — stale-result race: `_createCategoryTree`/`_createFilterTree` called unconditionally after `await` even if a newer fetch already started. Added `if (categoriesLoadId === searchModel.categoriesLoadId)` / `if (filtersLoadId === searchModel.filtersLoadId)` guards.
- `search_bar.js:763-766` **FIXED** — `onToggleSearchBar` wrote `showSearchBar` to `this.state` (which has no such property); actual state is `this.visibilityState`. Fixed to `this.visibilityState.showSearchBar = !this.visibilityState.showSearchBar`.
- `pager_hook.js:37` **FIXED** — fallback `{ total: 0 }` on `getProps()` returning falsy was incomplete; `Pager` requires `offset`, `limit`, and `onUpdate` too. Changed to `{ offset: 0, limit: 0, total: 0, onUpdate: () => {} }`.

**Status**: `[X]`

---

## Phase 5: services/ — Service Layer

### Group 17a — Services: Data

**Files**:
```
services/currency.js                    (110 lines)
services/title_service.js               (89 lines)
services/http_service.js                (66 lines)
services/localization_service.js        (135 lines)
services/name_service.js                (140 lines)
services/field_service.js               (269 lines)
services/user.js                        (371 lines)
services/orm_service.js                 (393 lines)
```

**Key questions**:
- `orm_service.js` (393 lines): is this a thin wrapper over RPC? Or does it add logic?
- `user.js` (371 lines): what does the user service expose? Session info, groups, preferences?
- `field_service.js` (269 lines): field definition fetching and caching — is the cache invalidated correctly?
- `name_service.js` (140 lines): what "names" does this service look up? Record display names?

**Findings**:
- `field_service.js:88` **FIXED** — `result.records` crash: `get_properties_base_definition` returns a plain array, not `{records:[...]}` like `webSearchRead`; `for (const record of undefined.records)` thrown. Added `Array.isArray(result) ? result : result.records` normalization.
- `orm_service.js:374` **FIXED** — `async` list contained dead `"nameGet"` (method removed from ORM class) and was missing 5 async methods: `webSave`, `webSaveMulti`, `webRead`, `searchCount`, `formattedReadGroupingSets`. The list drives the silent-proxy layer — stale entries cause unsilenced errors.
- `http_service.js:12` **FIXED** — Only HTTP 502 and 413 were caught; all other non-OK statuses (404, 500, 403, etc.) silently passed to `response[readMethod]()` which may parse error HTML as JSON. Added `!response.ok` guard as a catch-all after the specific cases.
- `debug_menu_items.js:32` **FIXED** — `activateTestsAssetsDebugging` read `router.current.debug` instead of `env.debug`; these diverge when debug mode is set programmatically (not via URL). Using `env.debug` is authoritative.
- `user.js:211` **FIXED** — `getAccessRightCacheKey(model, operation, ids)` omitted `context` from the cache key; after a company switch the context changes (new `allowed_company_ids`) but cached ACL results were reused under the same key, returning stale access rights. Added `context?.allowed_company_ids` as the 4th key component.
- `localization_service.js:112` **FIXED** — When cached translations exist, `fetchTranslations()` runs as a fire-and-forget background refresh; any rejection (network error, bad JSON) became an unhandled promise rejection silently swallowed by the runtime. Added `.catch()` to log a warning instead of losing the error.

**Status**: `[X]`

### Group 17b — Services: UI Support

**Files**:
```
services/scss_error_display.js           (69 lines)
services/file_upload_service.js          (178 lines)
services/sortable_service.js             (120 lines)
services/error_service.js               (192 lines)
services/tree_processor_service.js       (576 lines)
```

**Key questions**:
- `tree_processor_service.js` (576 lines): this is large for a service — what is a "tree processor"? Is this related to the domain tree or the menu tree?
- `error_service.js` (192 lines): how does it relate to `core/errors/`? Clear boundary?
- `file_upload_service.js` (178 lines): are uploads cancellable? Progress tracking?

**Findings**:
- `tree_processor_service.js:367` **FIXED** — `IN_RANGE_OPTIONS.find(([t]) => t === valueType)[1]` crashes with TypeError when `valueType` is unknown (returns undefined). Added null-check; falls back to `valueType` string.
- `tree_processor_service.js:370` **FIXED** — Off-by-one truncation: `.slice(0, limit)` gives exactly `limit` items, then `.map((val, index) => index < limit - 1 ? format : "...")` replaces the last real item with "..." even if no truncation occurred. Fixed: capture `allValues`, compare `allValues.length > limit`, only replace last slot if actually truncated.
- `file_upload_service.js:160` **FIXED** — XHR `error` event is a `ProgressEvent` with no `.error` property (`ev.error` is always `undefined`); `onError(undefined)` → notification with `undefined.message` crashes. Changed to `() => onError(null)`.
- `sortable_service.js:68` **FIXED** — Double-call crash: second `cleanup()` call → `boundElements.get(element)` returns `undefined` (deleted by first call) → `sortableId in undefined` throws TypeError. Added `boundElement &&` guard.
- `sortable_service.js:75` **FIXED** — Even with the crash guard, `cleanupFunctions.forEach((fn) => fn())` was called on both invocations; non-idempotent teardown hooks (timers, subscriptions) would fire twice. Changed to `cleanupFunctions.splice(0).forEach((fn) => fn())` which atomically drains the array before iterating.
- `tree_processor_service.js:423` **FIXED** — Recursive `getDomainTreeDescription` called on connector children without forwarding `limit`/`pathLimit`; deeply nested conditions always used `undefined` defaults, ignoring the caller's display budget. Threaded both params through the recursive call.

**Status**: `[X]`

### Group 17c — Services: Commands & Hotkeys

**Files**:
```
services/hotkeys/hotkey_hook.js          (21 lines)
services/hotkeys/hotkey_service.js       (427 lines)
services/commands/command_category.js    (20 lines)
services/commands/command_hook.js        (23 lines)
services/commands/default_providers.js   (147 lines)
services/commands/command_service.js     (283 lines)
services/commands/command_palette.js     (456 lines)
```

**Key questions**:
- `hotkey_service.js` (427 lines): key conflict resolution? Priority system?
- `command_palette.js` (456 lines): the Ctrl+K palette — fuzzy search implementation? Performance with many commands?
- `command_service.js` vs `command_palette.js`: service vs UI? Clear boundary?

**Findings**:
- `hotkey_service.js:307` **FIXED** — `overlayParent.style.position` crashes when `item.el.parentElement` is `null` (element detached from DOM). Added `if (!overlayParent) { continue; }` guard.
- `command_palette.js:88` **FIXED** — `hotkeyOptions: { type: String, optional: true }` causes Owl dev-mode prop validation crash when any command with `hotkeyOptions` (an object, not string) is shown. Changed to `type: Object`.
- `command_palette.js:292` **FIXED** — `nextIndex` is `undefined` if `type` is neither "NEXT" nor "PREV"; `selectCommand(undefined)` and `querySelector('#o_command_undefined')` returns null → crash. Added `else { return; }`.
- `command_palette.js:335` **FIXED** — `this.executeCommand(selectedCommand)` not awaited in `executeSelectedCommand`; errors from async command execution are silently dropped. Added `await`.
- `command_service.js:188` **FIXED** — `sameFullName` deduplication checks `"${name}(${id})"` (no space) but the format written at line 181 is `"${name} (${id})"` (with space); the lookup never matches → duplicate renames accumulate endlessly. Added space.

**Status**: `[X]`

### Group 17d — Services: Debug & Navigation

**Files**:
```
services/debug/debug_utils.js            (23 lines)
services/debug/debug_menu_basic.js       (68 lines)
services/debug/debug_menu.js             (73 lines)
services/debug/debug_providers.js        (73 lines)
services/debug/debug_menu_items.js       (111 lines)
services/debug/debug_context.js          (145 lines)
services/navigation/navigation.js        (445 lines)
```

**Key questions**:
- `navigation.js` (445 lines): what is the navigation service? URL management? Router adapter?
- Debug system: 6 files for debug tooling — is this complexity justified? Can it be consolidated?

**Findings**:
- `debug_menu.js:32` **FIXED** — Category logic used `item.type === "separator"` which never matches (items have `type: "item"`). `defaultCategories` was always `[]`; every palette item got `category: undefined`; no section headers appeared. Replaced with section-based grouping using `item.section` and `this.getSectionLabel()` (inherited from `DebugMenuBasic`), matching `configByNamespace.default.categoryNames` which the palette already supports.
- `debug_menu_items.js:32` **FIXED** — `router.current.debug` vs `env.debug` (see Group 17a findings).
- `navigation.js:248` **FIXED** — `item.el === document.activeElement` misses focused child inputs (e.g., search input inside a list item); `findIndex` returns -1 when focus is inside the container but not directly on `el`. Changed to `item.el.contains(document.activeElement)`.
- `navigation.js:333,345` **FIXED** — `this.activeItem = null` but the property is declared as `NavigationItem|undefined` (line 111). Inconsistent sentinel value; callers using `activeItem?.method()` are safe, but callers comparing `=== undefined` are not. Replaced all `null` assignments with `undefined`.

**Status**: `[X]`

### Group 17e — Services: PWA & Special

**Files**:
```
services/frequent_emoji_service.js
services/pwa/install_prompt.js
services/pwa/pwa_service.js              (247 lines)
services/install_scoped_app/
```

**Key questions**:
- `pwa_service.js` (247 lines): service worker registration, install prompt — are all PWA lifecycle events handled?
- `frequent_emoji_service.js`: why is this a service? Could it be a utility module?

**Findings**:
- `pwa_service.js:109` **FIXED** — `_removeInstallationState` called `JSON.parse(null)` (key absent) returning `null`; `delete null[key]` throws TypeError. Added `|| "{}"` fallback, matching `_setInstallationState`.
- `pwa_service.js:188-192` **FIXED** — Malformed CSS selector `"link[rel=manifest"` (missing `]`) and no null guard; `get(null, "text")` calls fetch with a null URL causing a network error. Fixed selector; added `if (!href) throw` guard.
- `pwa_service.js:153-154` **FIXED** — Stale captured `installationState` in `REGISTER_BEFOREINSTALLPROMPT_EVENT` closure; after `decline()`, the old value was still passed to `_handleBeforeInstallPrompt`, causing the prompt to re-appear. Changed to call `_getInstallationState()` fresh inside the callback.
- `pwa_service.js:122` **FIXED** — `path` param absent → `searchParams.get("path")` returns `null` → `state.startUrl = "/null"`. Added null guard with default fallback.
- `pwa_service.js:216-217` **FIXED** — `res.outcome` accessed without null guard; older browsers may return `undefined`. Added `res?.outcome` check.
- `install_scoped_app.js:40` **FIXED** — `encodeURIComponent(value)` + `URLSearchParams.set()` double-encodes (spaces become `%2520`). Removed `encodeURIComponent`; `URLSearchParams.set` handles encoding.
- `install_scoped_app.js:26-29` **FIXED** — `onMounted` async callback had no error handling; `getManifest()` failure leaves spinner permanently. Added try/catch with `console.error`.
- `install_scoped_app.js:25` **FIXED** — `this.isInstallationPossible` assigned but never used in template or methods. Removed dead assignment.

**Status**: `[X]`

---

## Phase 6: ui/ + components/ — Shared UI Layer

### Group 18 — UI Layer (All of ui/)

**Files** (20 files, 2566 lines):
```
ui/tooltip/tooltip.js                    (16 lines)
ui/tooltip/tooltip_hook.js               (18 lines)
ui/tooltip/tooltip_service.js            (289 lines)
ui/effects/rainbow_man.js                (80 lines)
ui/effects/effect_service.js             (93 lines)
ui/overlay/overlay_service.js            (77 lines)
ui/overlay/overlay_container.js          (114 lines)
ui/notification/notification.js          (100 lines)
ui/notification/notification_container.js (30 lines)
ui/notification/notification_service.js  (75 lines)
ui/popover/popover_hook.js               (72 lines)
ui/popover/popover_service.js            (86 lines)
ui/popover/popover.js                    (326 lines)
ui/dialog/confirmation_dialog.js         (118 lines)
ui/dialog/dialog_service.js              (116 lines)
ui/dialog/dialog.js                      (169 lines)
ui/block/block_ui.js                     (102 lines)
ui/block/ui_service.js                   (274 lines)
ui/bottom_sheet/bottom_sheet_service.js  (76 lines)
ui/bottom_sheet/bottom_sheet.js          (335 lines)
```

**Key questions**:
- `popover.js` (326 lines): uses `core/position/`? Is positioning correct on window resize?
- `dialog.js` vs `bottom_sheet.js`: are they using the same focus-trap and scroll-lock mechanism?
- `tooltip_service.js` (289 lines): memory leaks — are tooltips cleaned up when target unmounts?
- `ui_service.js` (274 lines): what does "UI service" mean? Block/unblock the UI?
- Overlay system: `overlay_service` + `overlay_container` — is this the mechanism for popover/dialog/bottom_sheet all sharing a container?

**Findings**:
- `notification.js:82-98` **FIXED** — Unbounded `requestAnimationFrame` loop: no cancellation handle stored; when the notification is destroyed externally (user dismisses), the rAF closure holds a stale `this` reference and continues firing, eventually calling `this.props.close()` on a destroyed component. Added `this._rafId`, stored the rAF ID on each iteration, and added `onWillDestroy(() => { this.startedTimestamp = false; cancelAnimationFrame(this._rafId); })`.
- `overlay_container.js:39-41` **FIXED** — `OVERLAY_ITEMS.splice(index, 1)` when `indexOf` returns `-1` (element already removed) silently removes the last overlay in the stack, corrupting all subsequent click-away containment checks. Added `if (index !== -1)` guard.
- `bottom_sheet.js:297-311` **FIXED** — Double-close: both `animationend` and `animationcancel` can fire in the same frame in some browser/CSS combinations, calling `this.props.close?.()` twice. The service's `bottomSheetCount` decrements twice, driving it below zero and removing CSS classes while other sheets may still be open. Replaced inline lambdas with a shared `onAnimDone` handler guarded by a `let animClosed = false` flag.
- `block_ui.js:35-37` **FIXED** — `messagesByDuration` array had `time: 180` (3 min) before `time: 120` (2 min), reversing the progressive message order. Users waiting between 2–3 minutes saw "Don't leave yet" before "You may not believe it", then it regressed. Swapped the two entries to ascending order.
- `bottom_sheet.js:83` **FIXED** — `window.history.pushState({ bottomSheet: true }, "")` called in `setup()` before the component mounts. If the bottom sheet is instantiated but not mounted (aborted dialog), a spurious history entry is created, breaking browser Back behavior. Moved into `onMounted()`.

**Status**: `[X]`

### Group 19 — Components: Dropdown & Navigation

**Files**:
```
components/dropdown/checkbox_item.js
components/dropdown/accordion_item.js
components/dropdown/dropdown_group.js
components/dropdown/_behaviours/dropdown_group_hook.js
components/dropdown/_behaviours/dropdown_nesting.js        (155 lines)
components/dropdown/_behaviours/dropdown_popover.js
components/dropdown/dropdown.js                             (416 lines)
components/tags_list/tags_list.js
components/notebook/notebook.js                             (216 lines)
components/pager/pager.js                                   (227 lines)
components/checkbox/checkbox.js                             (104 lines)
components/transition.js                                    (157 lines)
```

**Key questions**:
- `dropdown.js` (416 lines): trigger, items, nesting — is the nesting behavior in `_behaviours/` a clean separation?
- `pager.js` (227 lines): edge cases — 0 records, 1 page, very large totals?
- `notebook.js` (216 lines): tab panel — keyboard nav, ARIA roles?
- `transition.js` (157 lines): CSS transition hook? How does it interact with OWL rendering?

**Findings**:
- `notebook.js:119` **FIXED** — `this.pages.find((e) => e[0] === currentPage)[1]` crashes with TypeError when `currentPage` is stale (page removed between renders). This crashes the entire form view. Changed to `find(...)?.[1]` with optional chain, and guarded `page?.Component`.
- `dropdown_nesting.js:24-29` **FIXED** — `isOpen` setter fired `BUS.trigger("dropdown-opened", this)` on every assignment, including redundant ones (e.g. when reactive effect re-runs while already open). With many dropdowns, each spurious event triggers `handleChange` on all of them, creating O(n²) cascade on re-renders. Changed to only trigger on `false → true` transition: `if (!wasOpen && this._isOpen)`.
- `dropdown_nesting.js:91-96` **FIXED** — `current.activeEl` was set only inside a microtask-deferred `Promise.resolve().then(...)`. Before the microtask resolves, `activeEl === undefined` for all dropdowns. `shouldIgnoreChanges` uses `other.activeEl !== this.activeEl`; with both `undefined`, they're equal (not ignored), so unrelated dropdowns in different dialogs close each other on open. Added synchronous assignment before the async refresh.
- `transition.js:109-112` **FIXED** — Leave timer `browser.setTimeout(() => { state.shouldMount = false; onLeave(); }, leaveDuration)` fired after component destruction if the hosting component unmounted during a close animation. Added `onWillDestroy(() => browser.clearTimeout(timer))`.
- `notebook.js:159` **FIXED** — `if (v.index)` falsy check: pages with `index: 0` (first position) were never placed via the `pagesWithIndex` array, making it impossible to pin a tab at position 0. Changed to `if (v.index !== undefined)`.
- `notebook.js:165` **FIXED** — `this.disabledPages.push(k)` pushed the raw slot key `k` instead of the resolved `id` (`v.id || k`). When a slot has a custom `id`, the disabled check found no match and the tab remained clickable. Changed to push `id`.
- `checkbox.js:81` **FIXED** — `ev.composedPath().find((el) => [...].includes(el.tagName))` — `composedPath()` can include non-Element nodes (Window, Document, ShadowRoot, Text) whose `tagName` is `undefined`; in some browsers this throws. Added `el instanceof Element` guard before the tagName access.

**Status**: `[X]`

### Group 20 — Components: Complex Inputs

**Files**:
```
components/time_picker/time_picker.js                     (299 lines)
components/autocomplete/autocomplete.js                   (531 lines)
components/select_menu/select_menu.js                     (491 lines)
components/color_picker/color_picker.js                   (443 lines)
components/color_picker/custom_color_picker/custom_color_picker.js (740 lines)
components/datetime/datetime_picker_service.js            (621 lines)
components/datetime/datetime_picker.js                    (712 lines)
```

**Key questions**:
- `datetime_picker.js` (712 lines): the calendar widget — keyboard navigation? Accessibility?
- `datetime_picker_service.js` (621 lines): why is a picker a service? Position management?
- `custom_color_picker.js` (740 lines): HSL/HSV/RGB conversion — is it correct? Performance of canvas operations?
- `autocomplete.js` (531 lines): debouncing, loading state, keyboard navigation, screen reader announcements?
- `select_menu.js` (491 lines) vs `autocomplete.js` (531 lines): when to use which?

**Findings**:
- `custom_color_picker.js:61,68` **FIXED** — `setup()` wrote `this.props.defaultOpacity *= 100` and `this.props.defaultColor += opacityHex` directly onto the frozen (in dev) or shared props object. In production this silently corrupts the parent component's props on every re-render. Replaced with local instance variables `this._defaultOpacity` and `this._defaultColor`; updated all downstream references in `_updateRgba` and `_updateHsl`, and converted `this.props.selectedColor ||= this.props.defaultColor` to `this._selectedColor = this.props.selectedColor || this._defaultColor`.
- `autocomplete.js:303-351` **FIXED** — `do { navigate() } while (this.activeOption?.unselectable)` had no exit guard when `activeSourceOption` becomes `null`. When `activeSourceOption = null`, the else branch immediately sets it to the first available option, which may be unselectable again — theoretically cycling between null-assignment and first-option-selection indefinitely for edge-case source configurations. Added `&& this.state.activeSourceOption !== null` to the loop condition.
- `select_menu.js:364` **FIXED** — `this.state.choices.find((c) => c.value === value).label` throws TypeError when the selected value is absent from the filtered `state.choices` list (e.g. user types to search, then clicks a result that was filtered out of the local state). Changed to `?.label ?? ""`.
- `select_menu.js:292-293` **FIXED** — `this.menuRef.el.addEventListener("scroll", ...)` called on every `onStateChanged(true)` with a new anonymous arrow function. Each open stacks another listener since no cleanup removes the previous one. Replaced with AbortController: create on open, `abort()` on close.

**Status**: `[X]`

### Group 21 — Components: Domain/Tree Editors

**Files**:
```
components/tree_editor/tree_editor_autocomplete.js        (110 lines)
components/tree_editor/tree_editor_components.js          (103 lines)
components/tree_editor/tree_editor_value_editors.js       (485 lines)
components/tree_editor/tree_editor.js                     (360 lines)
components/domain_selector/domain_selector.js             (171 lines)
components/domain_selector/domain_selector_operator_editor.js
components/domain_selector_dialog/domain_selector_dialog.js (118 lines)
components/expression_editor/expression_editor.js         (150 lines)
components/expression_editor/expression_editor_operator_editor.js
components/model_field_selector/model_field_selector.js  (108 lines)
components/model_field_selector/model_field_selector_popover.js (413 lines)
```

**Key questions**:
- `tree_editor_value_editors.js` (485 lines): many different value editor types in one file — should each type be its own file?
- Relationship between `domain_selector` and `tree_editor` — is domain_selector a thin adapter over tree_editor?
- `model_field_selector_popover.js` (413 lines): field traversal (following relational chains) — depth limit? Circular relation protection?

**Findings**:
- `tree_editor_value_editors.js:338` **FIXED** — `shouldResetValue: (value) => parseValue(formatType, value) === value` had inverted logic: it returned `true` (reset) when the value parses correctly, so every valid numeric value was immediately reset to the default `1` — users could never enter a number for `integer`/`float`/`monetary` fields. Changed `===` to `!==`.
- `expression_editor.js:119` **FIXED** — `stringify: (value) => this.props.fields[value].string` crashed when `value` is `0` or `1` (the "always true/false" virtual conditions explicitly permitted by `isSupported`). The `fields` object is keyed by field name strings, so `fields[0]` is `undefined`. Changed to `fields[value]?.string ?? String(value)`.
- `domain_selector_dialog.js:96` **FIXED** — `await rpc("/web/domain/validate", ...)` rejection (network error, server 500) was uncaught: the button stayed disabled permanently since neither the `!isValid` re-enable path nor the success path ran. Wrapped the RPC call in try/catch; on error, re-enables the button and returns early.
- `model_field_selector_popover.js:180` **FIXED** — `searchInput.focus()` called without null guard inside `useEffect`; if `showSearchInput` is true but the search input element isn't present (layout not yet applied, or empty search page), this throws. Changed to `searchInput?.focus()`.
- `tree_editor_value_editors.js:287-289` **FIXED** — `extractProps` for `in`/`not in` non-relational fields mutated the shared `editorInfo` object in-place: `editorInfo.stringify = (val) => stringify(val, false)`. On subsequent renders with different values, the mutated stringify is used instead of the original, causing incorrect label display for items that should use the default disambiguation. Fixed by creating a local wrapper object: `const info = disambiguate(value) ? editorInfo : { ...editorInfo, stringify: (val) => editorInfo.stringify(val, false) }`.

**Status**: `[X]`

### Group 22 — Components: Media & Files

**Files**:
```
components/barcode/ZXingBarcodeDetector.js        (167 lines)
components/barcode/crop_overlay.js                (181 lines)
components/barcode/barcode_video_scanner.js        (245 lines)
components/file_viewer/file_model.js              (149 lines)
components/file_viewer/file_viewer.js             (280 lines)
components/file_input/file_input.js               (125 lines)
components/file_upload/file_upload_progress_container.js
components/signature/name_and_signature.js        (355 lines)
components/code_editor/code_editor.js             (208 lines)
components/errors/error_dialogs.js                (276 lines)
components/errors/error_handlers.js               (183 lines)
```

**Key questions**:
- `barcode_video_scanner.js` (245 lines): camera access — permission handling? Cleanup on unmount?
- `name_and_signature.js` (355 lines): canvas drawing — memory leaks? High-DPI handling?
- `code_editor.js` (208 lines): wraps CodeMirror/Ace? Is it properly destroyed?
- `error_dialogs.js` vs `error_handlers.js`: what's the difference?

**Findings**:
- `file_input.js:101` **FIXED** — `uploadFiles()` throws on network error → `isDisable` stays `true` forever, blocking all future uploads. Wrapped remaining upload code in try/finally.
- `barcode_dialog.js:55-68` **FIXED** — `scanBarcode()` promise hung forever when dialog closed without scan (neither `res` nor `rej` called). Fixed: (1) reordered `BarcodeDialog.onResult` to notify before closing (avoids race with `onClose`); (2) added `settled` flag + `onClose` rejection callback.
- `crop_overlay.js:93` **FIXED** — `firstChild` can be a text node (whitespace); `getComputedStyle(textNode)` throws TypeError. Changed to `firstElementChild`.
- `ZXingBarcodeDetector.js:122` **FIXED** — `format` returned as full `[key, value]` Map entry tuple instead of string; breaks API compatibility with native `BarcodeDetector`. Added `?.[0]` to extract key string; fallback to `"unknown"`.
- `file_viewer.js:261` **FIXED** — `document.write` with raw `defaultSource` interpolated into HTML attribute — XSS vector if source URL contains `"`. Replaced with DOM manipulation (`createElement("img")`, set `.src` programmatically).
- `error_dialogs.js:217` **FIXED** — `RedirectWarningDialog` destructures `data.arguments` without null guard; crash if `data` is undefined/null. Added early return with `this.props.close()`.
- `barcode_video_scanner.js:183` **FIXED** — On detector error, `onError` called but scan loop silently stopped (no rescheduling). Added explicit reschedule-and-return in the catch block.
- `file_viewer.js:118` **FIXED** — `this.state.file.isImage` throws when `state.file` is undefined (empty files array). Added `?.` optional chain.
- `error_dialogs.js:104,166` **FIXED** — Clipboard `writeText()` unhandled rejection (non-HTTPS/permission denied). Added `.catch(() => {})` to both `ErrorDialog` and `RPCErrorDialog`.
- `name_and_signature.js:154` **FIXED** — Initials from name with multiple consecutive spaces produced `undefined` initials. Added `.filter(Boolean)` before `.map(w => w[0])`.
- `name_and_signature.js:267` **FIXED** — `c.getContext("2d")` can return `null` (exhausted context limit); `ctx.drawImage(...)` throws. Added null guard.
- `name_and_signature.js:219` **FIXED** — `getDataURLFromFile` rejection unhandled in `onChangeSignLoadInput`. Wrapped in try/catch; sets `loadIsInvalid = true` on error.
- `code_editor.js:129,134` **FIXED** — Theme/readonly effects access `this.aceEditor` before it's initialized (editor-creation effect hasn't run yet on first render). Added `if (!this.aceEditor) return` guards.

**Status**: `[X]`

### Group 23 — Components: Layout & Selectors

**Files**:
```
components/dropzone/dropzone.js
components/dropzone/dropzone_hook.js              (111 lines)
components/action_swiper/action_swiper.js         (240 lines)
components/resizable_panel/resizable_panel.js     (230 lines)
components/record_selectors/record_autocomplete.js (144 lines)
components/record_selectors/multi_record_selector.js (103 lines)
```

**Findings**:
- `resizable_panel.js:119` **FIXED** — `getContainerRect()` returned `offsetLeft`-based parent-relative coordinates when `offsetParent` exists, but `onMouseMove` subtracted `ev.clientX` (viewport-relative), making every resize broken when the panel is not at `left: 0`. Replaced the `offsetParent` branch with `container.getBoundingClientRect()` throughout so both coordinates are viewport-relative.
- `multi_record_selector.js:74` **FIXED** — `getTags` created `onDelete: () => this.deleteTag(index)` capturing the `map()` position. If OWL patches the tag list by key reuse without re-running `getTags`, a stale closure deletes the wrong record. Changed to `this.deleteTag(this.props.resIds.indexOf(id))` which looks up the live index at deletion time using the stable record `id`.
- `dropzone_hook.js:82-88` **FIXED** — `useEffect(() => { hasTarget = !!el; updateDropzone(); }, () => [targetRef.el])` has no cleanup return. When the host component unmounts, OWL only runs the cleanup from the last effect run (which is `undefined` here), so an active overlay (file drag in progress) is never removed. Added `onWillUnmount` to call `removeDropzone()` if set.
- `action_swiper.js:215-221` **FIXED** — Rapid double-swipe (finger moves fast enough to trigger `handleSwipe` twice before the first `setTimeout` fires) queued two parallel action callbacks: both the `bounce` or `forwards` timer fired, running the action twice and calling `_reset()` twice. Added `browser.clearTimeout(this.actionTimeoutId)` at the top of `handleSwipe` before setting the new timeout.
- `record_autocomplete.js:58` **FIXED** — After `await this.lastProm`, if the host component unmounted during the RPC (e.g., dialog closed while typing), the continuation updated the name cache and created option closures that referenced `this.props.update` on a destroyed component. Added `this._mounted` flag (set to `false` in `onWillUnmount`); early-returns `[]` if unmounted after the await.

**Status**: `[X]`

---

## Phase 7: views/ — Widget Layer

### Group 24 — Views: Core System

**Files** (21 files, ~3.3K lines):
```
views/standard_view_props.js           (36)
views/module_views.js                  (41)
views/action_helper.js                 (21)
views/view_buttons.js                  (73)
views/widgets/standard_widget_props.js (9)
views/view_components/view_scale_selector.js (29)
views/view_components/report_view_measures.js (20)
views/view_components/selection_box.js (59)
views/widgets/ribbon/ribbon.js         (70)
views/view_button/multi_record_view_button.js (37)
views/widgets/widget.js                (153)
views/view_button/view_button_hook.js  (176)
views/view_components/multi_currency_popover.js (58)
views/view_button/view_button.js       (200)
views/view_components/multi_selection_buttons.js (265)
views/view_service.js                  (136)
views/multi_record_controller.js       (246)
views/view_hook.js                     (255)
views/view_utils.js                    (303)
views/debug_items.js                   (501)
views/view_compiler.js                 (502)
views/view.js                          (519)
```

**Status**: `[A]`

### Group 25 — Views: List

Split into two sub-groups due to size.

**Group 25a — List Support Files** (14 files, ~2.3K lines):
```
views/list/list_view.js               (58)
views/list/list_cog_menu.js           (22)
views/list/export_all/export_all.js   (45)
views/list/list_column_utils.js       (79)
views/list/list_group_layout.js       (130)
views/list/list_optional_fields.js    (140)
views/list/list_confirmation_dialog.js (134)
views/list/list_selection.js          (219)
views/list/list_aggregates_row.js     (179)
views/list/list_aggregates.js         (318)
views/list/list_virtualization.js     (230)
views/list/list_arch_parser.js        (343)
views/list/list_keyboard_edit.js      (345)
views/list/list_keyboard_nav.js       (547)
```

**Group 25b — List Core (Heavy)** (4 files, ~2.8K lines):
```
views/list/list_grid_state.js         (458)
views/list/column_width_hook.js       (473)
views/list/list_controller.js         (564)
views/list/list_renderer.js           (1540 — LARGEST NON-BLOB FILE)
```

**Status**: `[A]`

### Group 26 — Views: Kanban

**Files** (12 files, ~2.9K lines):
```
views/kanban/column_progress.js              (32)
views/kanban/kanban_cog_menu.js              (23)
views/kanban/kanban_view.js                  (59)
views/kanban/kanban_dropdown_menu_wrapper.js (35)
views/kanban/kanban_compiler.js              (206)
views/kanban/kanban_header.js                (188)
views/kanban/kanban_arch_parser.js           (287)
views/kanban/kanban_record_quick_create.js   (326)
views/kanban/kanban_record.js                (425)
views/kanban/kanban_controller.js            (440)
views/kanban/progress_bar_hook.js            (493)
views/kanban/kanban_renderer.js              (780)
```

**Status**: `[A]`

### Group 27 — Views: Pivot

**Files** (9 files, ~2.2K lines):
```
views/pivot/pivot_view.js              (78)
views/pivot/pivot_export.js            (70)
views/pivot/pivot_search_model.js      (53)
views/pivot/pivot_arch_parser.js
views/pivot/pivot_measurements.js      (154)
views/pivot/pivot_value_utils.js       (155)
views/pivot/pivot_group_tree.js        (124)
views/pivot/pivot_table.js             (151)
views/pivot/pivot_renderer.js          (392)
views/pivot/pivot_model.js             (1037)
```

**Status**: `[A]`

### Group 28 — Views: Calendar

**Files** (13 files, ~3.6K lines):
```
views/calendar/calendar_view.js                                (43)
views/calendar/calendar_renderer.js                            (63)
views/calendar/calendar_side_panel/calendar_side_panel.js      (67)
views/calendar/mobile_filter_panel/calendar_mobile_filter_panel.js (59)
views/calendar/calendar_common/calendar_common_week_column.js  (34)
views/calendar/calendar_year/calendar_year_popover.js          (130)
views/calendar/calendar_year/calendar_year_renderer.js         (237)
views/calendar/hooks/full_calendar_hook.js                     (72)
views/calendar/hooks/calendar_popover_hook.js                  (70)
views/calendar/hooks/square_selection_hook.js                  (267)
views/calendar/calendar_common/calendar_common_popover.js      (143)
views/calendar/calendar_filter_section/calendar_filter_section.js (197)
views/calendar/calendar_arch_parser.js                         (188)
views/calendar/calendar_common/calendar_common_renderer.js     (472)
views/calendar/calendar_controller.js                          (488)
views/calendar/calendar_model.js                               (1018)
```

**Status**: `[A]`

### Group 29 — Views: Graph

**Files** (7 files, ~1.8K lines):
```
views/graph/graph_view.js              (72)
views/graph/graph_search_model.js      (52)
views/graph/graph_controller.js        (78)
views/graph/graph_arch_parser.js
views/graph/graph_chart_config.js      (499)
views/graph/graph_renderer.js          (560)
views/graph/graph_model.js             (566)
```

**Status**: `[A]`

### Group 30 — Views: Dialogs & Settings

**Files** (included in Group 28+31 audit agent):
```
views/view_dialogs/select_create_dialog.js (142)
views/view_dialogs/form_view_dialog.js     (146)
views/view_dialogs/export_data_dialog.js   (511)
```

**Status**: `[A]`

---

## Phase 8: webclient/ + public/ — Application Shell

### Group 31 — Views: Form

**Files** (12 files, ~2.6K lines):
```
views/form/form_cog_menu/form_cog_menu.js                  (9)
views/form/setting/setting.js                              (76)
views/form/form_label.js                                   (76)
views/form/button_box/button_box.js                        (49)
views/form/status_bar_buttons/status_bar_buttons.js        (28)
views/form/form_error_dialog/form_error_dialog.js          (61)
views/form/form_status_indicator/form_status_indicator.js  (62)
views/form/form_view.js                                    (44)
views/form/form_arch_parser.js                             (73)
views/form/form_renderer.js                                (162)
views/form/form_compiler.js                                (763)
views/form/form_controller.js                              (690)
```

**Status**: `[A]`

### Group 32 — Webclient: Action System

**Files**:
```
webclient/actions/action_constants.js
webclient/actions/action_views.js
webclient/actions/skeleton_view.js       (52 lines)
webclient/actions/reports/utils.js       (55 lines)
webclient/actions/reports/report_action.js (62 lines)
webclient/actions/reports/report_hook.js   (73 lines)
webclient/actions/reports/report_executor.js (128 lines)
webclient/actions/client_actions.js        (122 lines)
webclient/actions/breadcrumb_manager.js    (210 lines)
webclient/actions/action_button_executor.js (208 lines)
webclient/actions/action_info_builders.js   (236 lines)
webclient/actions/debug_items.js            (225 lines)
webclient/actions/action_state.js           (193 lines)
webclient/actions/action_service.js         (1273 lines — 2nd LARGEST)
```

**Key questions**:
- `action_service.js` (1273 lines): state machine for navigation/actions — god file. What are the main concerns? Can controller stack, URL sync, and action execution be separated?
- `breadcrumb_manager.js`: separate from `action_state.js` — what's the split?
- Report actions: 4 files for reports — is that complexity justified?

**Status**: `[X]`

### Group 33 — Webclient: App Shell — `[X]`

**Files**:
```
webclient/density/density_service.js       (79 lines)
webclient/loading_indicator/               (70 lines)
webclient/burger_menu/burger_menu.js       (77 lines)
webclient/user_menu/user_menu.js           (53 lines)
webclient/user_menu/user_menu_items.js     (187 lines)
webclient/switch_company_menu/switch_company_item.js (51 lines)
webclient/switch_company_menu/switch_company_menu.js (417 lines)
webclient/menus/menu_providers.js          (87 lines)
webclient/menus/menu_helpers.js            (93 lines)
webclient/menus/menu_service.js            (141 lines)
webclient/navbar/navbar.js                 (273 lines)
webclient/webclient.js                     (236 lines)
```

**Key questions**:
- `switch_company_menu.js` (417 lines): company switching with multi-company — race conditions? State management?
- `webclient.js` (236 lines): root component — service startup order?

**Status**: `[ ]`

### Group 34 — Webclient: Reports, Debug & Clickbot

**Files**:
```
webclient/debug/debug_items.js             (72 lines)
webclient/debug/profiling/profiling_service.js (121 lines)
webclient/debug/profiling/profiling_qweb.js   (366 lines)
webclient/clickbot/clickbot.js              (557 lines)
```

**Key questions**:
- `clickbot.js` (557 lines): automated UI testing bot — is it safe to ship in production builds? Is it tree-shaken?
- `profiling_qweb.js` (366 lines): OWL rendering profiler — how does it hook into OWL internals?

**Status**: `[X]`

### Group 35 — Public Pages & Legacy — `[X]`

**Files**:
```
polyfills/clipboard.js
legacy/js/core/class.js
legacy/js/public/minimal_dom.js
legacy/js/public/lazyloader.js
legacy/js/public/public_root_instance.js
legacy/js/public/public_widget.js          (969 lines)
public/colibri.js                          (577 lines)
```

**Key questions**:
- `public_widget.js` (969 lines): old-style widget system for public pages — can anything be migrated to OWL?
- `class.js`: the old Odoo prototype-chain class system — is it still used?
- `colibri.js` (577 lines): what is Colibri? Likely a lightweight alternative to the full webclient for public pages.

**Status**: `[ ]`

---

## Appendix A: File Size Red Flags

Files above 500 lines are candidates for splitting. Priority for god-file extraction:

| File | Lines | Phase | Priority |
|------|-------|-------|----------|
| `views/list/list_renderer.js` | 1543 | 7 | CRITICAL |
| `fields/specialized/properties/properties_field.js` | 1098 | 3 | CRITICAL |
| `model/relational_model/record.js` | 1043 | 2 | CRITICAL |
| `search/search_model.js` | 1046 | 4 | CRITICAL |
| `webclient/actions/action_service.js` | 1273 | 8 | CRITICAL |
| `views/pivot/pivot_model.js` | 1037 | 7 | HIGH |
| `views/calendar/calendar_model.js` | 1020 | 7 | HIGH |
| `model/relational_model/relational_model.js` | 934 | 2 | HIGH |
| `model/relational_model/static_list.js` | 868 | 2 | HIGH |
| `core/utils/dnd/draggable_hook_builder.js` | 868 | 1 | HIGH |
| `views/kanban/kanban_renderer.js` | 781 | 7 | HIGH |
| `search/control_panel/control_panel.js` | 805 | 4 | HIGH |
| `search/search_bar/search_bar.js` | 779 | 4 | HIGH |
| `model/sample_server.js` | 761 | 2 | MEDIUM |
| `views/form/form_compiler.js` | 763 | 8 | MEDIUM |
| `views/form/form_controller.js` | 690 | 8 | MEDIUM |
| `components/datetime/datetime_picker.js` | 712 | 6 | MEDIUM |
| `fields/temporal/datetime/datetime_field.js` | 701 | 3 | MEDIUM |
| `views/graph/graph_model.js` | 572 | 7 | MEDIUM |
| `core/py_js/py_interpreter.js` | 507 | 1 | MEDIUM |

## Appendix B: Known Cross-File Patterns to Standardize

These inconsistencies were observed in the initial survey and must be addressed during each group's audit:

1. **`// @ts-check` coverage**: ~40% of files have it, ~60% don't. Phase 0 codemod adds it to all.
2. **`Object.hasOwn` vs `hasOwnProperty`**: mixed usage. Target: always `Object.hasOwn`.
3. **`for...of` vs `forEach`**: both used. Target: `for...of` (debuggable, no callback scope).
4. **String concatenation vs template literals**: some files still use `"a" + b`. Target: always template literals.
5. **`null` vs `undefined` for "no value"**: inconsistent. Document the convention per layer.
6. **Error constructor patterns**: some use `new Error(msg)`, some use custom error classes, some use `Object.assign(new Error(), {...})`. Standardize.
7. **Service factory pattern**: some return `{ method1, method2 }`, some return class instances. Standardize.
