// @ts-check
/** @odoo-module native */

/** @module @web/core/tree */

/**
 * The tree module's published interface.
 *
 * Everything under `core/tree/` that another addon imports today is re-exported here,
 * and nothing else. The names below are the contract; the 4 files behind them
 * are not, and may be renamed, split or moved without touching a
 * consumer OUTSIDE `web`. Inside it they are imported directly and a
 * rename does reach them — the face constrains other addons, which is
 * the only direction `js_face_boundary` enforces.
 *
 * Descriptive rather than aspirational: a face invented ahead of demand is a
 * guess. A consumer needing something not listed adds it here — one visible,
 * reviewable edit instead of a reach into a file.
 *
 * A face is a SIBLING file, not `tree/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/core/tree` to
 * `/web/static/src/core/tree.js` by appending `.js`, with no directory-index step.
 */

export {
    condition,
    connector,
    normalizeValue,
    operate,
    rewriteNConsecutiveChildren,
} from "./tree/condition_tree.js";
export {
    getInRangeProviderOptions,
    inRangeProviderRegistry,
    matchInRangeProviderOption,
    resolveInRangeProviderOption,
} from "./tree/in_range_providers.js";
export { getOperatorLabel } from "./tree/operator_labels.js";
export { virtualOperatorFunctions } from "./tree/virtual_operators.js";
