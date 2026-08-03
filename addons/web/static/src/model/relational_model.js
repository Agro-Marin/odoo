// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model */

/**
 * The relational model module's published interface.
 *
 * Everything under `model/relational_model/` that another addon imports today is re-exported here,
 * and nothing else. The names below are the contract; the 11 files behind them
 * are not, and may be renamed, split or moved without touching a
 * consumer OUTSIDE `web`. Inside it they are imported directly and a
 * rename does reach them — the face constrains other addons, which is
 * the only direction `js_face_boundary` enforces.
 *
 * Descriptive rather than aspirational: a face invented ahead of demand is a
 * guess. A consumer needing something not listed adds it here — one visible,
 * reviewable edit instead of a reach into a file.
 *
 * A face is a SIBLING file, not `relational_model/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/model/relational_model` to
 * `/web/static/src/model/relational_model.js` by appending `.js`, with no directory-index step.
 */

export { x2ManyCommands } from "./relational_model/commands.js";
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
export {
    addFieldDependencies,
    extractFieldsFromArchInfo,
    getFieldDomain,
    getFieldsSpec,
    makeActiveField,
    parseServerValue,
} from "./relational_model/utils.js";
