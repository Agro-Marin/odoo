// @ts-check
/** @odoo-module native */

/** @module @web/components/model_field_selector */

/**
 * The model field selector module's published interface.
 *
 * Everything under `components/model_field_selector/` that another addon imports today is re-exported here,
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
 * A face is a SIBLING file, not `model_field_selector/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/components/model_field_selector` to
 * `/web/static/src/components/model_field_selector.js` by appending `.js`, with no directory-index step.
 */

export { ModelFieldSelector } from "./model_field_selector/model_field_selector.js";
export { ModelFieldSelectorPopover } from "./model_field_selector/model_field_selector_popover.js";
