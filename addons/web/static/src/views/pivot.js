// @ts-check
/** @odoo-module native */

/** @module @web/views/pivot */

/**
 * The pivot module's published interface.
 *
 * Everything under `views/pivot/` that another addon imports today is re-exported here,
 * and nothing else. The names below are the contract; the 6 files behind them
 * are not, and may be renamed, split or moved without touching a
 * consumer OUTSIDE `web`. Inside it they are imported directly and a
 * rename does reach them — the face constrains other addons, which is
 * the only direction `js_face_boundary` enforces.
 *
 * Descriptive rather than aspirational: a face invented ahead of demand is a
 * guess. A consumer needing something not listed adds it here — one visible,
 * reviewable edit instead of a reach into a file.
 *
 * A face is a SIBLING file, not `pivot/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/views/pivot` to
 * `/web/static/src/views/pivot.js` by appending `.js`, with no directory-index step.
 */

export { PivotArchParser } from "./pivot/pivot_arch_parser.js";
export { PivotController } from "./pivot/pivot_controller.js";
export { getLeafCounts } from "./pivot/pivot_group_tree.js";
export { PivotModel } from "./pivot/pivot_model.js";
export { PivotRenderer } from "./pivot/pivot_renderer.js";
export { pivotView } from "./pivot/pivot_view.js";
