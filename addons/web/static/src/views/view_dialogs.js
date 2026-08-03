// @ts-check
/** @odoo-module native */

/** @module @web/views/view_dialogs */

/**
 * The view dialogs module's published interface.
 *
 * Everything under `views/view_dialogs/` that another addon imports today is re-exported here,
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
 * A face is a SIBLING file, not `view_dialogs/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/views/view_dialogs` to
 * `/web/static/src/views/view_dialogs.js` by appending `.js`, with no directory-index step.
 */

export { ExportDataDialog } from "./view_dialogs/export_data_dialog.js";
export { FormViewDialog } from "./view_dialogs/form_view_dialog.js";
export { SelectCreateDialog } from "./view_dialogs/select_create_dialog.js";
