# Phase 11 Audit: Relational + Specialized Fields

**Scope:** `fields/relational/` (20 files, ~3,527 lines) + `fields/specialized/` (20 files, ~4,268 lines)
**Total:** 40 files, ~7,795 lines

---

## Summary

| Severity | Found | Fixed |
|----------|-------|-------|
| [P1] Production crash | 2 | 2 |
| [P2] Edge-case crash/logic | 9 | 9 |
| [P3] Code quality | 5 | 0 |

---

## Findings and Fixes

### FIX-01 [P1] `Many2One` default `domain` prop type mismatch (crash on barcode scan)

**File:** `fields/relational/many2one/many2one.js:130`
**Issue:** `defaultProps.domain` was `[]` (Array) but the prop type is `Function` and `processScannedBarcode()` calls `this.props.domain()`. When `Many2One` is used standalone without a `domain` prop, `[].()` throws `TypeError: this.props.domain is not a function`.
**Fix:** Changed `domain: []` to `domain: () => []`.

### FIX-02 [P2] `x2many_dialog.js` async error leaves `recordIsOpen` stuck forever

**File:** `fields/relational/x2many_dialog.js:379-384`
**Issue:** `openRecord(params)` is async but the `try/catch` did `return openRecord(params)` without `await`. If `getFormViewInfo` rejects (e.g., network error after the first `await`), the promise rejects but `recordIsOpen` is never reset to `false`, permanently blocking the dialog from opening again.
**Fix:** Changed `return openRecord(params)` to `return await openRecord(params)`.

### FIX-03 [P2] `Many2ManyCheckboxesField.commitChanges` not pushed to `NEED_LOCAL_CHANGES` proms

**File:** `fields/relational/many2many_checkboxes/many2many_checkboxes_field.js:39-44`
**Issue:** `NEED_LOCAL_CHANGES` handler called `commitChanges()` but never pushed the returned promise to `ev.detail.proms`. Race condition: the parent save could proceed before checkbox changes were committed, causing data loss.
**Fix:** Wrapped handler to push the promise into `ev.detail.proms`.

### FIX-04 [P2] `PropertyValue.displayValue` crashes on orphaned selection value

**File:** `fields/specialized/properties/property_value.js:250`
**Issue:** `this.props.selection.find(...)[1]` crashes with `TypeError` when the stored value no longer exists in the selection options (e.g., an admin removed an option from the property definition while existing records still have it selected).
**Fix:** Changed to `?.find()?.[1] ?? value` for graceful fallback.

### FIX-05 [P2] `PropertyDefinition._typeLabel` crashes on unknown property type

**File:** `fields/specialized/properties/property_definition.js:497`
**Issue:** `allTypes.find(...)[1]` crashes if `propertyType` is not in the list (e.g., a type added by a custom module).
**Fix:** Changed to `?.find()?.[1] ?? propertyType`.

### FIX-06 [P2] `ReferenceField._fetchModelTechnicalName` crashes on deleted ir.model

**File:** `fields/relational/reference/reference_field.js:228-229`
**Issue:** `result[0].model` crashes if the ir.model record was deleted between cache population and access.
**Fix:** Changed to `result[0]?.model ?? false`.

### FIX-07 [P2] `ReferenceField._fetchReferenceCharData` crashes on deleted target record

**File:** `fields/relational/reference/reference_field.js:188-193`
**Issue:** `result[0].display_name` crashes if the referenced record was deleted. The cache stores the ORM promise, so the crash persists.
**Fix:** Added null guard: `if (!result[0]) { return false; }`.

### FIX-08 [P2] `ReferenceField` cache stores rejected promises permanently

**File:** `fields/relational/reference/reference_field.js:185-186, 225-226`
**Issue:** Both `specialDataCaches` entries stored raw promises. If the first ORM call fails (network error), the rejected promise is cached forever -- subsequent accesses always get the rejection, never retrying.
**Fix:** Added `.catch()` handler that clears the cache entry on error before re-throwing.

### FIX-09 [P2] `Many2ManyTagsField.onRecordSaved` crashes if tag removed during dialog

**File:** `fields/relational/many2many_tags/many2many_tags_field.js:112-115`
**Issue:** `records.find(...).load()` crashes if the record was removed from the many2many relation while the edit dialog was open (another user, concurrent tab).
**Fix:** Changed to optional chaining: `records.find(...)?.load()`.

### FIX-10 [P1] `JournalDashboardGraphField` crashes on empty/null field data

**File:** `fields/specialized/journal_dashboard_graph/journal_dashboard_graph_field.js:25`
**Issue:** `JSON.parse(null)` or `JSON.parse(false)` throws `SyntaxError`, crashing the entire component during setup. Subsequently, `this.data[0].values` would crash on empty arrays.
**Fix:** Added fallback `|| "[]"` for parse input, and early return in `renderChart()` when data is empty.

### FIX-11 [P2] `PropertiesField._movePopoverIfNeeded` crashes when popover not in DOM

**File:** `fields/specialized/properties/properties_field.js:889-900`
**Issue:** `document.querySelector(".o_field_property_definition").closest(".o_popover")` crashes with `TypeError: Cannot read properties of null` if the popover was closed in a race condition (e.g., property moved via keyboard while popover animation is in progress).
**Fix:** Added null guards with early return.

### FIX-12 [P2] `PropertyValue._nameGet` returns `undefined` for deleted records

**File:** `fields/specialized/properties/property_value.js:411-421`
**Issue:** If the comodel record was deleted, `result[0]` is `undefined`. The caller in `onValueChange` line 309 then accesses `newValue.id` on `undefined`, crashing.
**Fix:** Fallback to `{ id: recordId, display_name: false }` when `result[0]` is falsy.

---

## Not Fixed (P3 - Code Quality)

### NF-01 [P3] `PropertiesField._setDefaultPropertyValue` mutates `this.props`

**File:** `fields/specialized/properties/properties_field.js:1050`
Line `this.props.value = propertiesValues` directly mutates props (anti-pattern in OWL). The comment acknowledges this as a workaround. Fixing requires a broader refactor of the popover close timing.

### NF-02 [P3] `Many2ManyTagsField.deleteTagByIndex` declared `async` unnecessarily

**File:** `fields/relational/many2many_tags/many2many_tags_field.js:193`
The `async` keyword is unnecessary since the actual work happens inside `this.mutex.exec()`. Harmless.

### NF-03 [P3] `Many2One.onRecordSaved` passes potentially undefined `resId` to ORM

**File:** `fields/relational/many2one/many2one.js:157`
`this.props.value?.id` could be `undefined` if value is `false`. The handler is only invoked after opening a dialog for an existing record, so `value` should always be set in practice.

### NF-04 [P3] `ResUserGroupIdsField.getCategoryArch` injects unsanitized `category.name`

**File:** `fields/specialized/user_groups/res_user_group_ids_field.js:272-275`
Category names from the database are interpolated directly into XML strings without escaping. Low risk since `ir.module.category` names are admin-controlled.

### NF-05 [P3] `Many2ManyBinaryField.onFileUploaded` early-returns on first error

**File:** `fields/relational/many2many_binary/many2many_binary_field.js:72-81`
If multiple files are uploaded and one has an error, subsequent files (including valid ones) are not processed. Behavior may be intentional.

---

## Files Reviewed (40 total)

### Relational (20 files)
1. `many2one/many2one_field.js` - Clean
2. `many2one/many2one.js` - **FIX-01**
3. `many2x_autocomplete.js` - Clean
4. `x2many/x2many_field.js` - Clean
5. `x2many/list_x2many_field.js` - Clean
6. `x2many_crud.js` - Clean
7. `x2many_dialog.js` - **FIX-02**
8. `many2many_tags/many2many_tags_field.js` - **FIX-09**
9. `many2many_tags/kanban_many2many_tags_field.js` - Clean
10. `many2many_tags_avatar/many2many_tags_avatar_field.js` - Clean
11. `many2one_avatar/many2one_avatar_field.js` - Clean
12. `many2one_avatar/kanban_many2one_avatar_field.js` - Clean
13. `many2one_barcode/many2one_barcode_field.js` - Clean
14. `many2one_reference/many2one_reference_field.js` - Clean
15. `many2one_reference_integer/many2one_reference_integer_field.js` - Clean
16. `many2many_binary/many2many_binary_field.js` - NF-05
17. `many2many_checkboxes/many2many_checkboxes_field.js` - **FIX-03**
18. `relational_active_actions.js` - Clean
19. `special_data.js` - Clean
20. `reference/reference_field.js` - **FIX-06, FIX-07, FIX-08**

### Specialized (20 files)
21. `domain/domain_field.js` - Clean
22. `properties/properties_field.js` - **FIX-11**, NF-01
23. `properties/property_definition.js` - **FIX-05**
24. `properties/property_value.js` - **FIX-04, FIX-12**
25. `properties/property_tags.js` - Clean
26. `properties/property_definition_selection.js` - Clean
27. `properties/property_text.js` - Clean
28. `properties/calendar_properties_field.js` - Clean
29. `properties/card_properties_field.js` - Clean
30. `user_groups/res_user_group_ids_field.js` - NF-04
31. `user_groups/res_user_group_ids_popover.js` - Clean
32. `user_groups/res_user_group_ids_privilege_field.js` - Clean
33. `color_picker/color_picker_field.js` - Clean
34. `kanban_color_picker/kanban_color_picker_field.js` - Clean
35. `field_selector/field_selector_field.js` - Clean
36. `iframe_wrapper/iframe_wrapper_field.js` - Clean
37. `google_slide_viewer/google_slide_viewer.js` - Clean
38. `journal_dashboard_graph/journal_dashboard_graph_field.js` - **FIX-10**
39. `ir_ui_view_ace/ace_field.js` - Clean
40. `ace/ace_field.js` - Clean
