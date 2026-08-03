// @ts-check
/** @odoo-module native */

/** @module @web/views/kanban */

/**
 * The kanban view's published interface.
 *
 * Everything under `views/kanban/` that another addon imports today is
 * re-exported here, and nothing else. The names below are the contract; the
 * twelve files behind them are not, and may be renamed, split or moved without
 * touching a consumer OUTSIDE `web`. Inside it they are imported
 * directly and a rename does reach them — the face constrains other
 * addons, which is the only direction `js_face_boundary` enforces.
 *
 * This is deliberately descriptive rather than aspirational: it publishes what
 * is already depended on, because a face invented ahead of demand is a guess.
 * A consumer needing something not listed adds it here — one visible, reviewable
 * edit, instead of reaching into a file and creating a dependency nobody agreed
 * to.
 *
 * A face must be a SIBLING file, not `kanban/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/views/kanban` to
 * `/web/static/src/views/kanban.js` by appending `.js`, and performs no
 * directory-index resolution.
 */

export { AnimatedNumber } from "./kanban/animated_number.js";
export { ColumnProgress } from "./kanban/column_progress.js";
export {
    KANBAN_CARD_ATTRIBUTE,
    KanbanArchParser,
} from "./kanban/kanban_arch_parser.js";
export { KanbanColumnQuickCreate } from "./kanban/kanban_column_quick_create.js";
export { KanbanCompiler } from "./kanban/kanban_compiler.js";
export { KanbanController } from "./kanban/kanban_controller.js";
export { KanbanDropdownMenuWrapper } from "./kanban/kanban_dropdown_menu_wrapper.js";
export { KanbanHeader } from "./kanban/kanban_header.js";
export {
    CANCEL_GLOBAL_CLICK,
    KanbanRecord,
    getFormattedRecord,
    getImageSrcFromRecordInfo,
    getRawValue,
} from "./kanban/kanban_record.js";
export {
    KanbanQuickCreateController,
    KanbanRecordQuickCreate,
} from "./kanban/kanban_record_quick_create.js";
export { KanbanRenderer } from "./kanban/kanban_renderer.js";
export { kanbanView } from "./kanban/kanban_view.js";
