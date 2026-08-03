// @ts-check
/** @odoo-module native */

/** @module @web/fields/relational/many2one */

/**
 * The many2one module's published interface.
 *
 * Everything under `fields/relational/many2one/` that another addon imports today is re-exported here,
 * and nothing else. The names below are the contract; the 2 files behind them
 * are not, and may be renamed, split or moved without touching a
 * consumer OUTSIDE `web`. Inside it they are imported directly and a
 * rename does reach them — the face constrains other addons, which is
 * the only direction `js_face_boundary` enforces.
 *
 * Descriptive rather than aspirational: a face invented ahead of demand is a
 * guess. A consumer needing something not listed adds it here — one visible,
 * reviewable edit instead of a reach into a file.
 *
 * A face is a SIBLING file, not `many2one/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/fields/relational/many2one` to
 * `/web/static/src/fields/relational/many2one.js` by appending `.js`, with no directory-index step.
 */

export { computeM2OProps, KanbanMany2One, Many2One } from "./many2one/many2one.js";
export {
    buildM2OFieldDescription,
    extractM2OFieldProps,
    m2oSupportedOptions,
    Many2OneField,
    many2OneField,
} from "./many2one/many2one_field.js";
