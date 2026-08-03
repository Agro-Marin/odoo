// @ts-check
/** @odoo-module native */

/** @module @web/fields/display/progress_bar */

/**
 * The progress bar module's published interface.
 *
 * Everything under `fields/display/progress_bar/` that another addon imports today is re-exported here,
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
 * A face is a SIBLING file, not `progress_bar/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/fields/display/progress_bar` to
 * `/web/static/src/fields/display/progress_bar.js` by appending `.js`, with no directory-index step.
 */

export {
    KanbanProgressBarField,
    kanbanProgressBarField,
} from "./progress_bar/kanban_progress_bar_field.js";
export {
    ProgressBarField,
    progressBarField,
} from "./progress_bar/progress_bar_field.js";
