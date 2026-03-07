# Phase 9 Audit: Larger Components (~6,500 lines, 36 files)

## Scope
- `datetime/` (5 files, ~1,466 lines)
- `color_picker/` (4 files, ~1,267 lines)
- `tree_editor/` (5 files, ~1,120 lines)
- `dropdown/` (9 files, ~905 lines)
- `barcode/` (4 files, ~661 lines)
- `autocomplete/` (1 file, ~531 lines)
- `model_field_selector/` (2 files, ~521 lines)
- `select_menu/` (1 file, ~491 lines)
- `record_selectors/` (5 files, ~474 lines)

---

## Bugs Found and Fixed

### FIX-1: [P1] Color picker pointer coordinates wrong on scrolled pages
**File:** `color_picker/custom_color_picker/custom_color_picker.js`
**Lines:** 530-531, 602, 661

Three pointer-move handlers used `ev.pageY`/`ev.pageX` (document-relative coordinates) subtracted from `getClientRects()[0].top`/`.left` (viewport-relative coordinates). When the page is scrolled, the difference equals `window.scrollY/X`, causing the color picker pointer, hue slider, and opacity slider to track incorrectly -- the offset grows with scroll distance.

**Fix:** Changed `ev.pageY`/`ev.pageX` to `ev.clientY`/`ev.clientX` in all three handlers:
- `onPointerMovePicker()`
- `onPointerMoveSlider()`
- `onPointerMoveOpacitySlider()`

### FIX-2: [P2] DropdownItem props validation missing `type` key
**File:** `dropdown/dropdown_item.js`
**Line:** 37

```js
// BEFORE -- `Object` is treated as a key name, not a type validator
slots: { Object, optional: true },

// AFTER
slots: { type: Object, optional: true },
```

OWL's prop validation expects a `type` key. Without it, `Object` is a shorthand property name creating `{ Object: [Function Object], optional: true }`, which bypasses type checking entirely. This means any non-object value for `slots` would silently pass validation.

### FIX-3: [P2] SelectMenu mutates prop arrays via in-place `.sort()`
**File:** `select_menu/select_menu.js`
**Line:** 403

`filterOptions()` called `filteredOptions.sort(...)` on `group.choices` which is a direct reference to prop data. When `autoSort` is true and no search string is present, this mutates the parent component's choices array. Subsequent renders or parent-side reads of the array find it in a different order than originally specified.

**Fix:** Replaced `.sort()` with `.toSorted()` which returns a new array.

### FIX-4: [P3] Missing `break` in datetime picker service Tab handler
**File:** `datetime/datetime_picker_service.js`
**Line:** 275-283

The `case "Tab"` in `onInputKeydown` fell through silently when the condition was false (tabbing between two range inputs). While functionally harmless (exits the switch), the missing `break` violated the convention that every case either returns or breaks.

**Fix:** Added explicit `break` statement.

### FIX-5: [P3] `.sort()` mutation of `selectedRange` in datetime picker
**File:** `datetime/datetime_picker.js`
**Line:** 560

`this.selectedRange.sort()` mutated `selectedRange` in place. While safe because it's recreated each render, using `.toSorted()` is the modern non-mutating pattern and eliminates any risk if the code is refactored to reuse the array.

**Fix:** Changed to `.toSorted()`.

---

## Bugs Found -- Not Fixed (Require Broader Refactor)

### BUG-1: [P2] CustomColorPicker mutates `this.props` directly
**File:** `color_picker/custom_color_picker/custom_color_picker.js`
**Lines:** 60-76

```js
this.props.defaultOpacity *= 100;       // line 61
this.props.defaultColor += opacityHex;  // line 67
this.props.selectedColor = ...;         // line 75
```

Direct prop mutation is a fundamental anti-pattern in OWL. Props should be treated as immutable. If the parent re-reads these props (e.g., via a ref or reactive binding), it will see the mutated values. The correct approach would be to copy these into instance variables during setup.

**Impact:** Low in practice because the parent rarely re-reads these specific props after initial render. However, if the component is re-mounted or if `onWillUpdateProps` fires, the comparison logic at line 161 (`normalizeCSSColor(newSelectedColor) !== this.colorComponents.cssColor`) could produce incorrect results because `this.props.selectedColor` was already modified.

### BUG-2: [P2] tree_editor_value_editors: `extractProps` permanently mutates shared `editorInfo`
**File:** `tree_editor/tree_editor_value_editors.js`
**Lines:** 291-293

```js
extractProps: ({ value, update }) => {
    if (!disambiguate(value)) {
        const { stringify } = editorInfo;
        editorInfo.stringify = (val) => stringify(val, false);  // permanent mutation
    }
    ...
}
```

`extractProps` is called on each render. The first time `disambiguate(value)` returns false, `editorInfo.stringify` is permanently replaced. Even when the next render has `disambiguate(value) === true`, the original stringify is already lost. The closure captures the last assigned function, so subsequent overwrites create a chain of wrappers.

### BUG-3: [P2] `getPopoverTarget()` can NPE when `getInput(0)` returns null
**File:** `datetime/datetime_picker_service.js`
**Line:** 196

```js
let parentElement = getInput(0).parentElement;
```

`getInput(valueIndex)` returns `null` when the element is not connected. If this happens during range mode with no explicit target, accessing `.parentElement` throws `TypeError: Cannot read properties of null`.

### BUG-4: [P3] Calendar icon click listener accumulates on re-enable
**File:** `datetime/datetime_picker_service.js`
**Lines:** 143-149

```js
calendarIconGroupEl.addEventListener("click", () => open(0));
```

Each call to `enable()` adds a new anonymous click listener to the calendar icon without removing the previous one. The `useEffect(enable, getInputs)` calls `enable` whenever inputs change. While the function is identical in behavior, multiple listeners mean `open(0)` fires multiple times per click.

### BUG-5: [P3] Barcode scanner `isVideoReady()` has no timeout guard
**File:** `barcode/barcode_video_scanner.js`
**Lines:** 147-160

The `while (!isVideoElementReady(...))` loop polls indefinitely at 10ms intervals. If the camera stream is established but the video never reaches `readyState >= 2` (e.g., corrupted stream, hardware issue), this spins forever. The code has a FIXME comment acknowledging this. The component destruction check prevents leaks but not the CPU spin while mounted.

---

## Code Quality Observations (Not Bugs)

### OBS-1: [P3] `getStartOfWeek` weekday calculation
**File:** `datetime/datetime_picker.js`, line 98-105

The weekday calculation `date.weekday < weekStart ? weekStart - 7 : weekStart` correctly handles all ISO weekday values (1-7) relative to the locale's `weekStart`. No bug, but no input validation for `weekStart` being in the valid range.

### OBS-2: [P3] `numberRange` utility could use `Array.from`
**File:** `datetime/datetime_picker.js`, line 111

`[...Array(max - min)].map((_, i) => i + min)` -- works but `Array.from({length: max - min}, (_, i) => i + min)` is more idiomatic. Minor readability concern only.

### OBS-3: [P3] `toWeekItem` hardcodes day index 3 for week number
**File:** `datetime/datetime_picker.js`, line 154

`weekDayItems[3].range[0].weekNumber` -- uses the 4th day of the week to determine the week number. This is correct per ISO 8601 (the week is determined by the Thursday), but the comment explaining this rationale is missing.

### OBS-4: [P3] ZXingBarcodeDetector `format` returns `[key, val]` tuple
**File:** `barcode/ZXingBarcodeDetector.js`, line 122-124

`Array.from(ZXingFormats).find(([k, val]) => val === result.getBarcodeFormat())` -- returns a `[string, ZXingFormat]` tuple, not just the format string. The native `BarcodeDetector` API returns a plain string for `format`. This inconsistency between native and polyfill could cause issues in consuming code that expects a string.

### OBS-5: [P3] `isLitteralObject` -- typo in function name
**File:** `tree_editor/tree_editor_value_editors.js`, line 201

`isLitteralObject` should be `isLiteralObject` (single "t"). Internal-only function, so no API impact.

### OBS-6: [P3] `useDropdownGroup` -- unused `const` with incorrect `let` syntax
**File:** `dropdown/_behaviours/dropdown_group_hook.js`, line 23

```js
const /** @type {any} */ envAny = env;
```

This JSDoc type annotation syntax on a `const` declaration is unusual and only works because JSDoc treats it as a cast. Standard would be `/** @type {any} */ (env)`.

---

## Summary

| Severity | Found | Fixed | Deferred |
|----------|-------|-------|----------|
| [P1] Production | 1 | 1 | 0 |
| [P2] Edge case | 4 | 2 | 3 |
| [P3] Code quality | 2 + 6 obs | 2 | 6 obs |
| **Total** | **13** | **5** | **9** |

### Files Modified
1. `core/addons/web/static/src/components/color_picker/custom_color_picker/custom_color_picker.js` -- 3 edits (pageY/pageX -> clientY/clientX)
2. `core/addons/web/static/src/components/dropdown/dropdown_item.js` -- 1 edit (missing `type:` in props)
3. `core/addons/web/static/src/components/select_menu/select_menu.js` -- 1 edit (.sort -> .toSorted)
4. `core/addons/web/static/src/components/datetime/datetime_picker_service.js` -- 1 edit (missing break)
5. `core/addons/web/static/src/components/datetime/datetime_picker.js` -- 1 edit (.sort -> .toSorted)
