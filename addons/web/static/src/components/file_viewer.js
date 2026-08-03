// @ts-check
/** @odoo-module native */

/** @module @web/components/file_viewer */

/**
 * The file viewer module's published interface.
 *
 * Everything under `components/file_viewer/` that another addon imports today is re-exported here,
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
 * A face is a SIBLING file, not `file_viewer/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/components/file_viewer` to
 * `/web/static/src/components/file_viewer.js` by appending `.js`, with no directory-index step.
 */

export { FileModel, FileModelMixin } from "./file_viewer/file_model.js";
export { FileViewer } from "./file_viewer/file_viewer.js";
export { createFileViewer, useFileViewer } from "./file_viewer/file_viewer_hook.js";
