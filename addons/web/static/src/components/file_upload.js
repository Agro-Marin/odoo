// @ts-check
/** @odoo-module native */

/** @module @web/components/file_upload */

/**
 * The file upload module's published interface.
 *
 * Everything under `components/file_upload/` that another addon imports today is re-exported here,
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
 * A face is a SIBLING file, not `file_upload/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/components/file_upload` to
 * `/web/static/src/components/file_upload.js` by appending `.js`, with no directory-index step.
 */

export { FileUploadProgressBar } from "./file_upload/file_upload_progress_bar.js";
export { FileUploadProgressContainer } from "./file_upload/file_upload_progress_container.js";
export {
    FileUploadProgressDataRow,
    FileUploadProgressKanbanRecord,
} from "./file_upload/file_upload_progress_record.js";
