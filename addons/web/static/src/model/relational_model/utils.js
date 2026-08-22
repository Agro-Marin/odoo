// @ts-check
/** @odoo-module native */

export {
    getBasicEvalContext,
    getFieldContext,
    getFieldDomain,
    getId,
    isRelational,
} from "./field_context.js";
export {
    addFieldDependencies,
    combineModifiers,
    completeActiveFields,
    createPropertyActiveField,
    extractFieldsFromArchInfo,
    makeActiveField,
    patchActiveFields,
} from "./field_metadata.js";
export { getFieldsSpec } from "./field_spec.js";
export {
    AGGREGATABLE_FIELD_TYPES,
    extractAggregatesFromGroupData,
    extractInfoFromGroupData,
    fromUnityToServerValues,
    getAggregateSpecifications,
    getGroupServerValue,
    parseServerValue,
} from "./field_values.js";
