// @ts-check
/** @odoo-module native */

/** @module @web/views/list */

/**
 * The list module's published interface.
 *
 * Everything under `views/list/` that another addon imports today is re-exported here,
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
 * A face is a SIBLING file, not `list/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/views/list` to
 * `/web/static/src/views/list.js` by appending `.js`, with no directory-index step.
 */

export { processAllColumns } from "./list/list_column_utils.js";
export { ListController } from "./list/list_controller.js";
export { ListRenderer } from "./list/list_renderer.js";
export { listView } from "./list/list_view.js";
