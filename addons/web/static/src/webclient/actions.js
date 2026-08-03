// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions */

/**
 * The actions module's published interface.
 *
 * Everything under `webclient/actions/` that another addon imports today is re-exported here,
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
 * A face is a SIBLING file, not `actions/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/webclient/actions` to
 * `/web/static/src/webclient/actions.js` by appending `.js`, with no directory-index step.
 */

export { installActionCacheInvalidation } from "./actions/action_cache_invalidation.js";
export { ActionContainer } from "./actions/action_container.js";
export {
    ActionManager,
    actionService,
    clearUncommittedChanges,
    ControllerNotFoundError,
    makeActionManager,
    standardActionServiceProps,
} from "./actions/action_service.js";
export { downloadReport } from "./actions/reports/utils.js";
