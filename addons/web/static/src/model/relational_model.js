// @ts-check
/** @odoo-module native */

/**
 * The public face of the relational model.
 *
 * Everything a view, a field widget or a sibling repo needs is exported here,
 * from the module that defines it. There used to be a second barrel --
 * `relational_model/utils.js` -- re-exporting an overlapping set, and consumers
 * split roughly evenly between the two: `extractFieldsFromArchInfo` was
 * imported 8 times through this file and 7 times through that one, for the same
 * function. `named_export_coherence.py` proves either path resolves; nothing
 * said which to write, so both kept growing.
 *
 * Deep imports of `@web/model/relational_model/<module>` still work and are
 * still the right thing inside `model/` itself, where importing this file would
 * close a cycle back through `@web/model/model`. They are not the right thing
 * from outside it.
 */

export { DynamicGroupList } from "./relational_model/dynamic_group_list.js";
export { DynamicList } from "./relational_model/dynamic_list.js";
export { DynamicRecordList } from "./relational_model/dynamic_record_list.js";
export {
    getBasicEvalContext,
    getFieldContext,
    getFieldDomain,
    getSpecEvalContext,
    isRelational,
} from "./relational_model/field_context.js";
export {
    addFieldDependencies,
    combineModifiers,
    completeActiveFields,
    createPropertyActiveField,
    extractFieldsFromArchInfo,
    makeActiveField,
    patchActiveFields,
} from "./relational_model/field_metadata.js";
export { getFieldsSpec } from "./relational_model/field_spec.js";
export {
    AGGREGATABLE_FIELD_TYPES,
    extractAggregatesFromGroupData,
    extractInfoFromGroupData,
    fromUnityToServerValues,
    getAggregateSpecifications,
    getGroupServerValue,
    parseServerValue,
} from "./relational_model/field_values.js";
export { RelationalRecord } from "./relational_model/record.js";
export {
    preprocessMany2oneChanges,
    preprocessMany2OneReferenceChanges,
    preprocessReferenceChanges,
    preprocessX2manyChanges,
} from "./relational_model/record_preprocessors.js";
export { RelationalModel } from "./relational_model/relational_model.js";
export { resequenceRecords } from "./relational_model/resequence.js";
export { sortStaticList } from "./relational_model/static_list_sort.js";
export { listId } from "./relational_model/static_list_utils.js";
