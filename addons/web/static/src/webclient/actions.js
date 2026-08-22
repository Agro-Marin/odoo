// @ts-check
/** @odoo-module native */

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
