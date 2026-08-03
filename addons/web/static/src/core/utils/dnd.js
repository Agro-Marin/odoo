// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/dnd */

/**
 * The dnd module's published interface.
 *
 * Everything under `core/utils/dnd/` that another addon imports today is re-exported here,
 * and nothing else. The names below are the contract; the 5 files behind them
 * are not, and may be renamed, split or moved without touching a
 * consumer OUTSIDE `web`. Inside it they are imported directly and a
 * rename does reach them — the face constrains other addons, which is
 * the only direction `js_face_boundary` enforces.
 *
 * Descriptive rather than aspirational: a face invented ahead of demand is a
 * guess. A consumer needing something not listed adds it here — one visible,
 * reviewable edit instead of a reach into a file.
 *
 * A face is a SIBLING file, not `dnd/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/core/utils/dnd` to
 * `/web/static/src/core/utils/dnd.js` by appending `.js`, with no directory-index step.
 */

export { useDraggable } from "./dnd/draggable.js";
export {
    DRAGGED_CLASS,
    makeNativeDraggableHook,
} from "./dnd/draggable_hook_builder.js";
export { makeDraggableHook } from "./dnd/draggable_hook_builder_owl.js";
export { useNestedSortable } from "./dnd/nested_sortable.js";
export { useSortable } from "./dnd/sortable_owl.js";
