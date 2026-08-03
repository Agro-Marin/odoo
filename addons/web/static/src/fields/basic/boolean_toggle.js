// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/boolean_toggle */

/**
 * The boolean toggle module's published interface.
 *
 * Everything under `fields/basic/boolean_toggle/` that another addon imports today is re-exported here,
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
 * A face is a SIBLING file, not `boolean_toggle/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/fields/basic/boolean_toggle` to
 * `/web/static/src/fields/basic/boolean_toggle.js` by appending `.js`, with no directory-index step.
 */

export {
    BooleanToggleField,
    booleanToggleField,
} from "./boolean_toggle/boolean_toggle_field.js";
export {
    ListBooleanToggleField,
    listBooleanToggleField,
} from "./boolean_toggle/list_boolean_toggle_field.js";
