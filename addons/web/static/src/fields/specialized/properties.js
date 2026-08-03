// @ts-check
/** @odoo-module native */

/** @module @web/fields/specialized/properties */

/**
 * The properties module's published interface.
 *
 * Everything under `fields/specialized/properties/` that another addon imports today is re-exported here,
 * and nothing else. The names below are the contract; the 3 files behind them
 * are not, and may be renamed, split or moved without touching a
 * consumer OUTSIDE `web`. Inside it they are imported directly and a
 * rename does reach them — the face constrains other addons, which is
 * the only direction `js_face_boundary` enforces.
 *
 * Descriptive rather than aspirational: a face invented ahead of demand is a
 * guess. A consumer needing something not listed adds it here — one visible,
 * reviewable edit instead of a reach into a file.
 *
 * A face is a SIBLING file, not `properties/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/fields/specialized/properties` to
 * `/web/static/src/fields/specialized/properties.js` by appending `.js`, with no directory-index step.
 */

export { PropertiesField } from "./properties/properties_field.js";
export { PropertyDefinition } from "./properties/property_definition.js";
export { PropertyValue } from "./properties/property_value.js";
