# Phase PC-03 — `core/network/` + `core/l10n/` + `core/py_js/` Audit Output

**Scope**: `static/src/core/network/` (5 files) + `static/src/core/l10n/` (10 files) + `static/src/core/py_js/` (9 files)
**File count**: 24
**Status**: COMPLETE — 1 bug fixed, 0 SKIPs

Files:
`network/rpc.js`, `network/rpc_cache.js`, `network/rpc_dedup.js`,
`network/content_disposition.js`, `network/download.js`,
`l10n/localization.js`, `l10n/translation.js`, `l10n/time.js`,
`l10n/date_utils.js`, `l10n/date_serialization.js`, `l10n/utils.js`,
`l10n/utils/locales.js`, `l10n/utils/normalize.js`, `l10n/utils/format_list.js`,
`l10n/dates.js`,
`py_js/py.js`, `py_js/py_builtin.js`, `py_js/py_date.js`, `py_js/py_date_helpers.js`,
`py_js/py_interpreter.js`, `py_js/py_parser.js`, `py_js/py_timedelta.js`,
`py_js/py_tokenizer.js`, `py_js/py_utils.js`

---

## Fixed Findings

---

### `py_js/py_date.js:345` — [P1] C-08 — `PyTime.strftime` `%m` adds spurious `+1` to already 1-indexed month

**Code**:
```js
case "m":
    return fmt2(this.month + 1);   // month is already 1-indexed!
```

**Problem**: `PyTime` inherits from `PyDate` via `super(year, month, day)` where the constructor receives `month = now.getMonth() + 1` (already converted from JS 0-indexed to Python 1-indexed). Adding another `+1` in `strftime` causes `%m` to output month + 1, e.g. January → `"02"`, December → `"13"`. This breaks `datetime.now().strftime("%m")` in every domain expression and QWeb template using `PyTime`. The parent class `PyDate.strftime` at line 97 correctly uses `fmt2(this.month)` — the subclass had a divergent copy.

**Fix**:
```js
case "m":
    return fmt2(this.month);
```

---

## Files with No Findings

`network/rpc.js`, `network/rpc_cache.js`, `network/rpc_dedup.js`,
`network/content_disposition.js` (vendored, `eslint-disable`), `network/download.js` (vendored section),
`l10n/localization.js`, `l10n/translation.js`, `l10n/time.js`,
`l10n/date_utils.js`, `l10n/date_serialization.js`, `l10n/utils.js`,
`l10n/utils/locales.js`, `l10n/utils/normalize.js`, `l10n/utils/format_list.js`,
`l10n/dates.js`,
`py_js/py.js`, `py_js/py_builtin.js`, `py_js/py_date_helpers.js`,
`py_js/py_interpreter.js`, `py_js/py_parser.js`, `py_js/py_timedelta.js`,
`py_js/py_tokenizer.js`, `py_js/py_utils.js`
