# Phase 1 Audit Report: Core Infrastructure (Deep Pass)

> **Date**: 2026-03-07
> **Auditor**: Claude Opus 4.6 (8 parallel deep-audit agents, line-by-line)
> **Files audited**: ~130 files across 8 sub-areas
> **Findings**: 21 Critical/High, 52 Medium, 60+ Low

---

## Executive Summary

The deep audit uncovered significantly more issues than the initial pass. The most
critical findings are:

1. **Concurrency primitives have fundamental correctness bugs** — Mutex deadlocks on
   synchronous throws, Race clobbers subsequent races from stale callbacks, debounce
   leaks promises
2. **py_js evaluator has O(n²) performance** — every binary/unary operator creates a
   full new evaluation context; the tokenizer recompiles its regex on every call
3. **Router click handler breaks standard browser behavior** — Ctrl+click, middle-click
   intercepted; history entries missing state
4. **`sprintf` produces "undefined" literals** for excess `%s` placeholders (documented
   as producing empty strings)
5. **Dead code**: `rpc_dedup.js` is never imported; `nameGet` ghost in ORM service async list

---

## Severity Summary

| Severity | Count | Key Areas |
|----------|-------|-----------|
| **Critical** | 6 | Mutex sync-throw deadlock, Race stale-callback clobber, py_js prototype leakage (×4) |
| **High** | 15 | Router click handler, py_js O(n²) perf, batched first-call-wins, sprintf "undefined", PyDate no validation, missing builtins, scrollTo hang, waitUntil CPU leak, abort double-event, dead rpc_dedup.js, nameGet ghost, `roundPrecision(NaN)=0`, `%W`/`%w` wrong mapping, TranslatedString JSON bug, stale-while-revalidate |
| **Medium** | 52 | Across all areas |
| **Low** | 60+ | Edge cases, dead code, style, documentation |

---

## CRITICAL FINDINGS (must fix)

### 1. Mutex: synchronous throw deadlocks `getUnlockedDef()` forever
**File**: `core/utils/concurrency.js:119-124`

If `action()` throws synchronously, the throw exits `always()` before `.finally()` is
attached. `_queueSize` is never decremented, `_unlock()` never fires, and
`getUnlockedDef()` hangs forever.

```js
// FIX:
const always = () => {
    let result;
    try { result = action(); }
    catch (e) { result = Promise.reject(e); }
    return Promise.resolve(result).finally(() => {
        if (--this._queueSize === 0) this._unlock();
    });
};
```

### 2. Race: stale callbacks clobber subsequent races
**File**: `core/utils/concurrency.js:169-180`

When a promise from a completed race settles late, the resolver/rejecter closures
still hold references to `this.currentProm`, `this.currentPromResolver`, and
`this.currentPromRejecter`. They null these out and call `resolve()`/`reject()` on a
potentially **new** race's internal promise, corrupting it.

```js
// FIX: use a generation counter
add(promise) {
    if (!this.currentProm) {
        this._gen = (this._gen || 0) + 1;
        const gen = this._gen;
        // ... in resolver/rejecter:
        if (this._gen !== gen) return; // stale — ignore
    }
}
```

### 3-6. py_js: prototype chain leakage (4 vectors)
**Files**: `core/py_js/py_interpreter.js:454,477,144,381`

- Bracket access `obj["constructor"]` → leaks Object constructor
- Dot access `obj.constructor` → same via ObjLookup fallthrough
- `in` operator uses JS `in` (traverses prototype chain)
- `evalContext = Object.create(context)` exposes prototype properties as variables

All fixed with a property blocklist + `Object.hasOwn()` + `Object.create(null)`.

---

## HIGH FINDINGS (should fix soon)

### 7. py_js: O(n²) performance from `evaluate()` per operator
**File**: `core/py_js/py_interpreter.js:36,155`

`applyUnaryOp` and `applyBinaryOp` call the **top-level** `evaluate()` instead of the
inner `_evaluate()`, creating a new `Set`, `Object.create()`, `defineProperty`, and
closure for every single operator in an expression. For `1 + 2 + 3 + 4 + 5`, this is
5 full evaluation contexts.

**Fix**: Refactor to pass `_evaluate` as a parameter or make them closures inside `evaluate()`.

### 8. py_js: tokenizer recompiles regex on every call
**File**: `core/py_js/py_tokenizer.js:264`

`new RegExp(PseudoToken, "g")` is created inside `tokenize()`. The pattern is constant.
Move to module scope and reset `lastIndex = 0`.

### 9. py_js: parser uses `tokens.shift()` — O(n) per token
**File**: `core/py_js/py_parser.js:370`

Array `shift()` moves all remaining elements. For 20 tokens, this is 200 element moves.
Replace with index-based consumption: `let pos = 0; tokens[pos++]`.

### 10. Router: click handler intercepts Ctrl+click / middle-click
**File**: `core/browser/router.js:325-357`

No check for `ev.button !== 0`, `ev.ctrlKey`, `ev.metaKey`, `ev.shiftKey`, `ev.altKey`.
Ctrl+click (open in new tab) is turned into SPA navigation.

### 11. Router: click handler pushes empty history state
**File**: `core/browser/router.js:350`

`browser.history.pushState({}, "", url.href)` — should push `{nextState: state}` like
`doPush()` does. Back/forward to these entries re-parses URL instead of restoring state.

### 12. Router: `cast()` parses hex, Infinity, whitespace
**File**: `core/browser/router.js:29-31`

- `cast("0x1f")` → 31 (hex parsing)
- `cast("Infinity")` → Infinity
- `cast("  42  ")` → 42 (whitespace trimmed)
- `cast(" ")` → 0 (whitespace-only string)

### 13. Router: `sanitize()` double-casts, corrupts booleans and single-element arrays
**File**: `core/browser/router.js:70`

`cast(true)` → 1, `cast(false)` → 0. `cast([42])` → 42 (single-element array to number).

### 14. Router: popstate handler doesn't reset `pushArgs`
**File**: `core/browser/router.js:290-305`

Cancels pending push timeout but accumulated `pushArgs.state` persists, leaking stale
state into the next `pushState` call.

### 15. `batched()` is first-call-wins for arguments
**File**: `core/utils/timing.js:17-24`

Only the first call's `args` reach the callback. Subsequent calls within the batch
window are completely ignored. Surprising for a "batched" utility.

### 16. `debounce.cancel()` doesn't null `handle`
**File**: `core/utils/timing.js:87-92`

After `cancel()`, the next call sees `handle` as a stale (cleared) timer ID. Since
`!handle` is false, the leading edge doesn't fire.

### 17. `sprintf` produces "undefined" for excess `%s`
**File**: `core/utils/format/strings.js:222,269`

`sprintf("%s and %s", "a")` → `"a and undefined"`. Documented as producing empty
strings. `String.raw` converts missing substitutions to `"undefined"`.

### 18. `PyDate` / `PyDateTime` constructors have no validation
**File**: `core/py_js/py_date.js:48-52,201-209`

`new PyDate(2024, 13, 1)` silently creates an invalid date. Python raises `ValueError`.

### 19. py_js: missing essential builtins
**File**: `core/py_js/py_builtin.js:34`

Missing `len`, `abs`, `int`, `float`, `str`, `round` — commonly used in Odoo domains.

### 20. `scrollTo` promise hangs if no scroll occurs
**File**: `core/utils/dom/scrolling.js:96-100`

If element is already at the right position, `scrollend` never fires.

### 21. `waitUntil` rAF loop never stops after timeout race
**File**: `core/utils/macro.js:83-101,166`

`Promise.race([executeStep(), launchTimer()])` — when timer wins, the `waitUntil` rAF
loop continues forever, burning CPU at 60fps.

### 22. RPC: abort causes double `RPC:RESPONSE` event
**File**: `core/network/rpc.js:207-216`

XHR abort fires `error` event before `abort` event. Both paths trigger `RPC:RESPONSE`.

### 23. `rpc_dedup.js` is dead code — never imported
**File**: `core/network/rpc_dedup.js`

No file imports it. `rpc_cache.js` has its own deduplication.

### 24. ORM service: `nameGet` ghost in async list
**File**: `services/orm_service.js:377`

`name_get` was removed in Odoo 17. Still listed in the service async array.

### 25. `roundPrecision(NaN)` silently returns 0
**File**: `core/utils/format/numbers.js:54`

`if (!value) return 0` — catches NaN, false, null, "". NaN should propagate or throw.

### 26. `%W` and `%w` strftime-to-Luxon mappings are wrong
**File**: `core/l10n/dates.js:71-72`

Python `%W` (Monday-start week, 00-53) ≠ Luxon `WW` (ISO week, 01-53).
Python `%w` (Sunday=0) ≠ Luxon `c` (Monday=1).

### 27. `TranslatedString` JSON serialization returns untranslated source
**File**: `core/l10n/translation.js:140-191`

`JSON.stringify(new TranslatedString("Hello"))` uses the `[[StringData]]` slot (source
language), not `valueOf()`. Fix: add `toJSON() { return this.valueOf(); }`.

### 28. Stale-while-revalidate causes mid-session translation changes
**File**: `services/localization_service.js:112-120`

Background translation fetch mutates `translatedTerms` mid-session. No mechanism to
re-render components. Same string can show different translations on the same page.

---

## MEDIUM FINDINGS (52 total — highlights)

### Concurrency & Timing
- **Mutex re-entrant deadlock**: `exec()` inside `exec()` callback deadlocks forever (concurrency.js:109-127)
- **Mutex never-resolving action**: permanently deadlocks the mutex, no timeout (concurrency.js:119-126)
- **KeepLast `await` leak**: callers using `await` on superseded promises suspend indefinitely, leaking stack frames (concurrency.js:38-53)
- **`throttleForAnimation` promise leak**: overwriting `lastCall` abandons previous `resolve` (timing.js:164)
- **`throttleForAnimation` throw inconsistency**: leading-edge throw rejects promise, trailing-edge throw leaves it pending (timing.js:148 vs 162)
- **`setRecurringAnimationFrame` silent death**: callback throw kills the loop with no recovery (timing.js:106-108)

### py_js
- **Division by zero → Infinity/NaN** instead of error (py_interpreter.js:226-234)
- **`is`/`is not` operators not implemented** — common Python idiom (py_interpreter.js:237-248)
- **`isIn` with Set uses `in` operator** instead of `has()` — always false (py_interpreter.js:137-148)
- **`isLess` doesn't handle PyDate/PyDateTime** — uses JS object comparison, always wrong (py_interpreter.js:88-104)
- **No recursion depth limit** — stack overflow possible (py_interpreter.js)
- **`max()`/`min()` with no args → -Infinity/Infinity** instead of error (py_builtin.js:75-88)
- **`max()`/`min()` only work with numbers** — `max("a","b")` → NaN (py_builtin.js:75-89)
- **`PyTime extends PyDate`** — architecturally wrong, inherits year/month/day (py_date.js:333)
- **`strftime` missing `%%` handling** — literal percent not supported (py_date.js:92)
- **`leapDays` vs `leapdays` case mismatch** in relativedelta (py_date.js:437-438)
- **`substract` misspelling** throughout all date classes (py_date.js:109)
- **AST type magic numbers** — no shared enum, silent bugs if out of sync

### Router
- **`parseString` doesn't decode keys** — only values are `decodeURIComponent()`-decoded (router.js:43-44)
- **`parseString` empty string produces phantom key** — `parseString("")` → `{"": ""}` (router.js:38-49)
- **Debounced push sticky `replace` flag** — `||=` means any `replace:true` in batch wins (router.js:395)
- **`computeNextState` leaks `undefined` into actionStack** — `sanitizeSearch` only cleans top-level (router.js:60-63)
- **`splice(indexOf(x), 1)` without -1 guard** — removes wrong element if key not found (router.js:165-170)
- **`urlToState()` mutates passed URL object** (router.js:176-256)
- **`startRouter()` called at module load** — side effects on import (router.js:435)

### Collections & Formatting
- **`omit` uses `for...in`** — copies inherited prototype properties (objects.js:84)
- **`deepMerge` returns `undefined`** for non-objects — docstring says extension wins (objects.js:127-130)
- **`shallowEqual(new Date(0), new Date(1000))` → true** — Date/Map/Set have 0 own keys (objects.js:14-24)
- **`rotate` on empty array → NaN** — division by zero in modulo (arrays.js:280)
- **`range(0, 10, 0)` → infinite loop** — no guard for step=0 (numbers.js:30-37)
- **`mixCssColors` crash on invalid input** — `false.red` → TypeError (colors.js:327-335)
- **`convertRgbToHsl` uses non-exclusive if statements** — correct by coincidence (colors.js:59-66)
- **`humanNumber` depends on translation length** — `_t("kMGTPE")` must be exactly 6 chars (numbers.js:192)
- **`formatDuration` month hack** — replaces first "m" in string, locale-dependent (dates.js:337)

### Hooks & DOM
- **`useAutofocus` throws on email/date input types** — `setSelectionRange` fails (hooks.js:79-86)
- **`_protectMethod` returns never-settling promise** — leaks memory (hooks.js:158)
- **`useSpellCheck` never clears elements array** between effect runs (hooks.js:215-245)
- **`useOwnedDialogs` accumulates callbacks** — never removed on normal close (hooks.js:297-309)
- **`scrollTo` returns `undefined` vs `Promise`** inconsistently (scrolling.js:93)
- **`getTabableElements` misses contenteditable** elements (ui.js:125-140)
- **`measureTextWidth` doesn't copy input's font** — inherits parent's font (autoresize.js:77-91)

### Network & RPC
- **HTTP 502 handled but other 5xx errors produce misleading `ConnectionLostError`** (rpc.js:158-164)
- **No JSON-RPC 2.0 validation** — `jsonrpc: "2.0"` and `id` not checked (rpc.js:175-176)
- **`jsonEqual` non-deterministic** — `JSON.stringify` key order dependent (rpc_cache.js:17-19)
- **ORM async list incomplete** — missing `webRead`, `webSave`, `searchCount` (orm_service.js:374-387)
- **Unhandled promise rejection** in localization service translation fetch (localization_service.js:112)
- **`grouping` JSON.parse without try/catch** — crashes web client on invalid data (localization_service.js:100)

### Reactive & Patch
- **`Reactive` class breaks private fields** in subclasses — Proxy identity mismatch (reactive.js:27-29)
- **`effect()` can cause infinite loops** — no re-entrant guard (reactive.js:39-43)
- **`macro.advance()` is recursive** — can stack overflow for many-step macros (macro.js:176)
- **IndexedDB `_execute` can recurse infinitely** if table creation fails (indexed_db.js:150-167)
- **IndexedDB errors silently swallowed** — `read()` returns `undefined` on failure (indexed_db.js:185-191)

---

## Prioritized Fix List

### Batch 1: Critical (breaks correctness or security)
| # | File | Issue | Effort |
|---|------|-------|--------|
| 1 | concurrency.js | Mutex sync-throw deadlock | Small |
| 2 | concurrency.js | Race stale-callback clobber | Small |
| 3 | py_interpreter.js | Property blocklist for bracket/dot access | Small |
| 4 | py_interpreter.js | `in` operator → `Object.hasOwn()` | Small |
| 5 | py_interpreter.js | `evalContext` → `Object.create(null)` | Small |
| 6 | py_interpreter.js | Recursion depth limit | Small |

### Batch 2: High (significant bugs or perf)
| # | File | Issue | Effort |
|---|------|-------|--------|
| 7 | py_interpreter.js | Refactor binary/unary ops to use inner `_evaluate` | Medium |
| 8 | py_tokenizer.js | Move regex to module scope | Small |
| 9 | py_parser.js | Index-based token consumption | Medium |
| 10 | router.js | Click handler: check button + modifier keys | Small |
| 11 | router.js | Push `{nextState: state}` in click handler | Small |
| 12 | router.js | Stricter `cast()` | Small |
| 13 | timing.js | `debounce.cancel()` null handle + lastArgs | Small |
| 14 | timing.js | Document batched first-call-wins or change to last-call-wins | Small |
| 15 | strings.js | Pad sprintf substitutions to prevent "undefined" | Small |
| 16 | py_date.js | Add constructor validation | Small |
| 17 | py_builtin.js | Add `len`, `abs`, `int`, `float`, `str`, `round` | Medium |
| 18 | scrolling.js | Timeout fallback for scrollend | Small |
| 19 | macro.js | AbortSignal for waitUntil | Medium |
| 20 | rpc.js | Abort flag to prevent double RPC:RESPONSE | Small |
| 21 | rpc_dedup.js | Delete dead file | Small |
| 22 | orm_service.js | Remove nameGet, add missing async methods | Small |
| 23 | numbers.js | `roundPrecision`: distinguish NaN from zero | Small |
| 24 | dates.js | Fix `%W`/`%w` mappings or document limitation | Small |
| 25 | translation.js | Add `toJSON()` to TranslatedString | Small |

### Batch 3: Medium (correctness, consistency) — 52 items
See full list above. Most are small-effort fixes.

---

## Refactoring Opportunities

### py_js: Major refactor recommended
1. **Shared AST type enum** — replace magic numbers 0-15 with named constants
2. **Index-based parser** — eliminate O(n²) `shift()` calls
3. **Inline binary/unary evaluation** — eliminate redundant `evaluate()` contexts
4. **Module-level regex** — compile once, reset `lastIndex`
5. **AST cache** — `Map<string, AST>` for repeated expression evaluation
6. **Fix "substract" → "subtract"** across all date classes

### Concurrency: Hardening pass
1. **Mutex**: try/catch wrapper for synchronous throws
2. **Race**: generation counter for stale callback protection
3. **KeepLast**: reject superseded promises with `CancelledError`
4. **debounce**: proper cleanup in `cancel()`

### Router: Modernization
1. **`Object.create(null)`** in `parseString` for prototype safety
2. **`decodeURIComponent`** for both keys and values
3. **Stricter `cast()`** — `Number.isFinite(n) && String(n) === value`
4. **Reset `pushArgs`** in popstate handler
