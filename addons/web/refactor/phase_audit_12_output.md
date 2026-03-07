# Phase 12 Audit: `core/addons/web/static/src/fields/`

**Scope**: basic/ + temporal/ + media/ + selection/ + display/ + hooks/ + root (~70 files)
**Auditor**: Claude Opus 4.6
**Date**: 2026-03-07

---

## Summary

| Severity | Count | Fixed |
|----------|-------|-------|
| [P1] Production bug | 3 | 3 |
| [P2] Edge case bug | 2 | 1 |
| [P3] Code quality | 4 | 1 |

---

## Findings

### F-01 [P1] `formatInteger` crashes on `isPassword` option — `value.length` on a number

**File**: `formatters.js:248`
**Category**: C-02 (type error)

`formatInteger` is declared for integer values (numbers), but the `isPassword` branch calls `value.length`. Numbers don't have a `.length` property, so this returns `undefined`, and `"*".repeat(undefined)` returns `""` — the password mask silently fails.

**Before**:
```js
if (options.isPassword) {
    return "*".repeat(value.length);
}
```

**After**:
```js
if (options.isPassword) {
    return "*".repeat(String(value).length);
}
```

**Fixed**: Yes

---

### F-02 [P1] GaugeField `extractProps` reads wrong option name — `max_field` vs `max_value_field`

**File**: `display/gauge/gauge_field.js:135`
**Category**: C-01 (incorrect identifier)

The `supportedOptions` array declares the option as `"max_value_field"` (line 124), but `extractProps` reads `options.max_field` (line 135). The option is never read, so the `maxValueField` prop is always `undefined` and the gauge always falls back to `maxValue` (default 100). Users configuring `max_value_field` in view XML get silently ignored.

**Before**:
```js
maxValueField: options.max_field,
```

**After**:
```js
maxValueField: options.max_value_field,
```

**Fixed**: Yes

---

### F-03 [P1] `StateSelectionField.label` uses first character instead of full state value for legend lookup

**File**: `selection/state_selection/state_selection_field.js:68-77`
**Category**: C-02 (incorrect indexing)

The `label` getter builds a legend key using `this.props.record.data[this.props.name][0]`, which indexes into the state string (e.g., `"blocked"`) and returns only the first character (`"b"`). It then looks for `legend_b` instead of `legend_blocked`. The `options` getter on line 58 correctly uses the full state value, showing this is unintentional.

For Kanban state fields, common values are `"normal"`, `"done"`, `"blocked"`. The legend lookup would search for `legend_n`, `legend_d`, `legend_b` — none of which exist. The label silently falls through to `formatSelection()`, so custom legend labels set on the record are never shown.

**Before**:
```js
get label() {
    if (
        this.props.record.data[this.props.name] &&
        this.props.record.data[
            `legend_${this.props.record.data[this.props.name][0]}`
        ]
    ) {
        return this.props.record.data[
            `legend_${this.props.record.data[this.props.name][0]}`
        ];
    }
    return formatSelection(this.currentValue, { selection: this.options });
}
```

**After**:
```js
get label() {
    const stateValue = this.props.record.data[this.props.name];
    if (stateValue && this.props.record.data[`legend_${stateValue}`]) {
        return this.props.record.data[`legend_${stateValue}`];
    }
    return formatSelection(this.currentValue, { selection: this.options });
}
```

**Fixed**: Yes

---

### F-04 [P2] `FileUploader.onFileChange` uploads zero-size files after warning

**File**: `file_handler.js:54-62`
**Category**: C-04 (missing control flow)

When a file has zero size, the code warns the user and logs to console, but does NOT skip the file. Execution continues to `this.props.onUploaded()`, sending empty data to the server. The record gets updated with an empty base64 string, potentially overwriting valid data.

**Before**: Warning shown but upload proceeds.

**After**: Added `this.state.isUploading = false; continue;` after the zero-size warning to skip to the next file.

**Fixed**: Yes

---

### F-05 [P2] `evaluateMathematicalExpression` ignores locale decimal separator in `=` expressions

**File**: `parsers.js:19-36`
**Category**: C-05 (locale handling gap)

The function uses native `parseFloat()` (line 28) which only recognizes `.` as decimal separator. For users with comma-decimal locales, `=1,5+2,5` is parsed as `=1+2` because `parseFloat("1,5")` returns `1`. The regular `parseNumber` function (used for non-expression values) correctly handles locale separators. This only affects the `=` mathematical expression feature.

**Not fixed**: Fixing this requires rethinking the tokenizer to handle locale-aware numbers within expressions, which is a larger design change. The split on `[-+*/()^]` cannot distinguish between a comma decimal point and a comma that might be part of expression syntax.

---

### F-06 [P3] `FileUploader.onFileChange` returns `null` instead of `void`

**File**: `file_handler.js:50`
**Category**: M-01 (inconsistency)

The `checkSize` early return uses `return null` while the empty-files early return at line 46 uses `return`. Event handler return values are unused, so this is cosmetic, but inconsistent.

**Fixed**: Yes (changed to `return`)

---

### F-07 [P3] `TranslationDialog.domain` getter references undeclared props and mutates them

**File**: `translation_dialog.js:70-77`
**Category**: M-02 (dead code)

The `domain` getter references `this.props.domain` and `this.props.searchName`, neither of which are declared in the component's `props` schema. The getter is never called — `loadTranslations` does not use it. Additionally, it mutates `this.props.domain` via `push()`, which would violate OWL's immutability principle if it were called.

**Not fixed**: Dead code, harmless. Would break nothing if removed but that's out of audit scope.

---

### F-08 [P3] `BinaryField.getDownloadData` passes filename value as `filename_field`

**File**: `media/binary/binary_field.js:65`
**Category**: C-03 (semantic mismatch)

`filename_field` in the download data is set to `this.fileName` (the actual filename string), but the server's `/web/content` endpoint expects `filename_field` to be the field name (e.g., `"report_name"`) from which to read the filename. The server may fall back to the `filename` parameter, masking the issue.

**Not fixed**: This is a longstanding pattern that appears to work via server fallback. Changing it risks breaking the download flow and requires verifying the server endpoint behavior.

---

### F-09 [P3] `parseNumber` replaces ALL occurrences of locale decimal point

**File**: `parsers.js:80`
**Category**: C-05 (overly aggressive replacement)

The decimal point replacement uses the `"g"` flag:
```js
value = value.replace(new RegExp(escapeRegExp(options.decimalPoint), "g"), ".");
```

If a user types multiple decimal points (e.g., `1.2.3`), all are replaced with `.`, yielding `1.2.3` which becomes `NaN` — correctly caught by the fallback. However, if the decimal point is a comma and thousands separator is a period (German locale: `1.234,56`), after stripping `.` (thousands) we get `1234,56`, then replacing `,` gives `1234.56` — correct. No actual bug, just noting the `"g"` flag is intentional for edge case safety.

**Not fixed**: Not a bug, functioning as intended.

---

## Files Audited (70 total)

### Root (~15 files)
- `parsers.js` — All 5 parsers audited (parseFloat, parseInteger, parseFloatTime, parsePercentage, parseMonetary)
- `formatters.js` — All 18 formatters audited (**F-01 fixed**)
- `field.js` — Field component, parseFieldNode, fieldVisualFeedback
- `field_types.js` — X2M_TYPES constant
- `field_tooltip.js` — getTooltipInfo
- `field_utils.js` — extractDigits, extractNumericOptions
- `field_widths.js` — FIELD_WIDTHS, computeOptimalDateWidths
- `standard_field_props.js` — Props schema
- `file_handler.js` — FileUploader (**F-04, F-06 fixed**)
- `input_field_hook.js` — useInputField
- `numpad_decimal_hook.js` — useNumpadDecimal
- `dynamic_placeholder_hook.js` — useDynamicPlaceholder
- `dynamic_placeholder_popover.js` — DynamicPlaceholderPopover
- `translation_button.js` — TranslationButton
- `translation_dialog.js` — TranslationDialog (**F-07 noted**)

### basic/ (~16 files)
- `text_input_field_base.js`, `numeric_input_field_base.js`
- `char/char_field.js`, `text/text_field.js`
- `integer/integer_field.js`, `float/float_field.js`
- `monetary/monetary_field.js`, `percentage/percentage_field.js`
- `float_time/float_time_field.js`, `float_factor/float_factor_field.js`
- `float_toggle/float_toggle_field.js`
- `boolean/boolean_field.js`, `boolean_toggle/boolean_toggle_field.js`, `boolean_toggle/list_boolean_toggle_field.js`
- `email/email_field.js`, `phone/phone_field.js`, `url/url_field.js`
- `color/color_field.js`, `copy_clipboard/copy_clipboard_field.js`
- `html/html_field.js`, `json/json_field.js`

### temporal/ (~4 files)
- `datetime/datetime_field.js`, `datetime/list_datetime_field.js`
- `remaining_days/remaining_days_field.js`
- `timezone_mismatch/timezone_mismatch_field.js`

### display/ (~9 files)
- `badge/badge_field.js`
- `progress_bar/progress_bar_field.js`, `progress_bar/kanban_progress_bar_field.js`
- `handle/handle_field.js`
- `percent_pie/percent_pie_field.js`
- `gauge/gauge_field.js` (**F-02 fixed**)
- `stat_info/stat_info_field.js`
- `statusbar/statusbar_field.js`
- `contact_statistics/contact_statistics.js`

### media/ (~6 files)
- `binary/binary_field.js` (**F-08 noted**)
- `image/image_field.js`
- `pdf_viewer/pdf_viewer_field.js`
- `contact_image/contact_image_field.js`
- `signature/signature_field.js`
- `attachment_image/attachment_image_field.js`

### selection/ (~10 files)
- `selection_like_field.js`
- `selection/selection_field.js`, `selection/filterable_selection_field.js`
- `radio/radio_field.js`
- `label_selection/label_selection_field.js`
- `state_selection/state_selection_field.js` (**F-03 fixed**)
- `badge_selection/badge_selection_field.js`, `badge_selection/list_badge_selection_field.js`
- `badge_selection_with_filter/badge_selection_field_with_filter.js`
- `priority/priority_field.js`

### hooks/ (~1 file)
- `record_observer.js`
