# Phase 3 Redo — core/l10n/ + core/py_js/ Audit Output

**Scope**: `static/src/core/l10n/` (10 files) + `static/src/core/py_js/` (9 files)
**File count**: 19
**Status**: COMPLETE — 1 P2 bug fixed, 1 P3 fixed, 8 deferred

---

## Fixed Findings

---

### `py_date.js:279-307` + `py_interpreter.js:210` — [P2] C-01 — PyDateTime subtraction returns NaN instead of PyTimeDelta

**Problem**: `PyDateTime` does not extend `PyDate`. The interpreter's `-` operator checked
`left instanceof PyDate` (false for PyDateTime), fell through to `return left - right`,
producing `NaN`. In Python, `datetime - datetime` returns a `timedelta`.

**Fix**:
1. Added `PyDateTime.substract(other)` handling both PyTimeDelta and PyDateTime args
2. Added `PyDateTime.toordinal()` using existing `ymd2ord`
3. Updated `applyBinaryOp` `-` case to include `left instanceof PyDateTime`

---

### `py_interpreter.js:55` — [P3] M-02 — Comment had duplicate "dict" in type order

---

## Previous Findings Verified

1. `py_date.js` strftime `%m` off-by-one — CONFIRMED FIXED
2. `dates.js:71-72` `%W`/`%w` approximate mapping — ACKNOWLEDGED (no fix available)
3. `dates.js:333-338` formatDuration fragile replacement — ACKNOWLEDGED

---

## Documented (Not Fixed)

| Sev | Location | Description |
|-----|----------|-------------|
| P2 | py_interpreter.js | `is`/`is not` operators parse but throw at evaluation |
| P2 | time.js:76 | `roundMinutes(0)` sets minute to NaN |
| P3 | py_tokenizer.js:196 | `~` incorrectly in binaryOperators |
| P3 | py_parser.js/interpreter | Bitwise ops parse but don't evaluate |
| P3 | py_date.js:377,415,528 | `leapdays` vs `leapDays` case mismatch (works by accident) |
| P3 | dates.js | Unmapped strftime codes silently produce literals |
| P3 | py_utils.js:39-46 | `toPyValue` wraps Date in String AST node |
| P3 | py_parser.js:405 | `parseArgs([null])` treats null as kwargs |
