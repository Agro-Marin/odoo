// @ts-check
/** @odoo-module native */

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
