// @ts-check
/** @odoo-module native */

export { DynamicGroupList } from "./relational_model/dynamic_group_list.js";
export { DynamicList } from "./relational_model/dynamic_list.js";
export { DynamicRecordList } from "./relational_model/dynamic_record_list.js";
export { getSpecEvalContext } from "./relational_model/field_context.js";
export { RelationalRecord } from "./relational_model/record.js";
export {
    preprocessMany2oneChanges,
    preprocessMany2OneReferenceChanges,
    preprocessReferenceChanges,
    preprocessX2manyChanges,
} from "./relational_model/record_preprocessors.js";
export { RelationalModel } from "./relational_model/relational_model.js";
export { resequence } from "./relational_model/resequence.js";
export { sort } from "./relational_model/static_list_sort.js";
export { listId } from "./relational_model/static_list_utils.js";
export {
    addFieldDependencies,
    extractFieldsFromArchInfo,
    getFieldDomain,
    getFieldsSpec,
    makeActiveField,
    parseServerValue,
} from "./relational_model/utils.js";
