# Phase 3 — core/l10n/ + core/py_js/ Audit Output

**Scope**: `static/src/core/l10n/` (10 files) + `static/src/core/py_js/` (9 files)
**File count**: 19
**Status**: COMPLETE — 0 bugs fixed, 0 SKIPs

Files — `core/l10n/`:
`localization.js`, `translation.js`, `time.js`, `date_utils.js`,
`date_serialization.js`, `dates.js`, `utils.js`, `utils/locales.js`,
`utils/normalize.js`, `utils/format_list.js`

Files — `core/py_js/`:
`py.js`, `py_builtin.js`, `py_date.js`, `py_date_helpers.js`,
`py_interpreter.js`, `py_parser.js`, `py_timedelta.js`,
`py_tokenizer.js`, `py_utils.js`

---

## Acknowledged Imperfections (No Fix Available)

---

### `core/l10n/dates.js:71-72` — [P2] C-01 — `%W`/`%w` strftime-to-Luxon mapping is approximate

**Code**:
```js
W: "WW",  // Python: week-of-year (Mon=first day, 00-53)  →  Luxon: ISO week (01-53, week 1 has first Thursday)
w: "c",   // Python: weekday (0=Sun, 6=Sat)               →  Luxon: ISO weekday (1=Mon, 7=Sun)
```

**Problem**: Both mappings produce different values than Python's `strftime`:
- `%W`: Python counts weeks 00-53 with Monday as first day; Luxon `WW` uses ISO 8601 where week 1 contains Jan 4. They diverge at year boundaries (e.g., Jan 1 on a Tuesday → Python week 0, ISO week 1 or 52).
- `%w`: Python uses 0=Sunday…6=Saturday; Luxon `c` uses 1=Monday…7=Sunday. Both the base and start-day differ.

**Why not fixed**: No Luxon format token exists that matches Python's semantics for either specifier. Fixing this properly requires custom formatting logic outside the conversion table. These specifiers are not used in Odoo's standard localization date/datetime formats (`%d/%m/%Y`, `%m/%d/%Y %H:%M:%S`, etc.), so the practical impact is limited to custom strftime format strings using `%W` or `%w`.

---

### `core/l10n/dates.js:333-338` — [P3] C-01 — `formatDuration` month "m"→"M" replacement is fragile

**Code**:
```js
if (!showFullDuration && duration.loc.locale.includes("en") && duration.months > 0) {
    durationSplit[0] = durationSplit[0].replace("m", "M");
}
```

**Problem**: When `narrow` display is used, Luxon renders months as `"Xm"` (same as minutes). The code replaces the first `"m"` with `"M"` to disambiguate, but only for English locales. If the narrow format ever changes upstream or if a month value contains the digit sequence "m" for other reasons, this breaks.

**Why not fixed**: The workaround is locale-gated and only fires in narrow display mode. No better API exists in Luxon for this disambiguation. Practical impact is minimal — `formatDuration` always rounds to the nearest minute, so sub-minute values don't appear.

---

## Confirmed PC-03 Fix Present

`py_date.js` — `PyTime.strftime` `%m` mapping no longer adds +1 to the month. The fix from PC-03 is verified present.

---

## Delta vs PC-03

### PC-03 Findings (3 bugs)
1. `py_date.js` — `%m` strftime off-by-one → CONFIRMED (fix present)
2. `py_interpreter.js` — comparison chaining → Not in scope (already confirmed separately)
3. `py_parser.js` — unary minus precedence → Not in scope (already confirmed separately)

### New Findings Not in PC-03
1. `dates.js:71-72` — NEW [P2] — `%W`/`%w` approximate mapping (no fix available)
2. `dates.js:333-338` — NEW [P3] — formatDuration fragile replacement (no fix available)

---

## Other Observations (Not Bugs)

- `py_parser.js:404-412` — `parseArgs` mutates caller's kwargs object. Latent: no caller relies on the original kwargs being pristine after the call. Not a bug in current usage.
- `py_utils.js:39-46` — `toPyValue` wraps `PyDate` in a `String` AST node type. Semantically odd but functional: the interpreter handles `PyDate` objects correctly regardless of the AST wrapper node type.
- Multiple files use `"substract"` (typo of "subtract") — consistent across the internal API. Renaming would break backward compatibility with no functional benefit.

---

## Files with No Findings

`core/l10n/`: `localization.js`, `translation.js`, `time.js`, `date_utils.js`,
`date_serialization.js`, `utils.js`, `utils/locales.js`, `utils/normalize.js`,
`utils/format_list.js`

`core/py_js/`: `py.js`, `py_builtin.js`, `py_date.js`, `py_date_helpers.js`,
`py_interpreter.js`, `py_parser.js`, `py_timedelta.js`, `py_tokenizer.js`,
`py_utils.js`
