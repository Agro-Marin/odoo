// @ts-check
/** @odoo-module native */

/** @import { Action, BaseView } from "./action_service.js" */

/**
 * @param {BaseView[]} views
 * @param {boolean} multiRecord
 * @param {string} [viewType]
 * @returns {BaseView|undefined}
 */
export function findView(views, multiRecord, viewType) {
    return views.find((v) => v.type === viewType && v.multiRecord === multiRecord);
}

/**
 * @param {Action} action
 * @param {import("@web/core/registry").Registry<import("registries").ActionsRegistryItemShape>} actionRegistry
 * @returns {"current"|"fullscreen"|"new"|"main"}
 */
export function getActionMode(action, actionRegistry) {
    if (action.target === "new") {
        return "new";
    }
    if (action.type === "ir.actions.client") {
        const clientAction = actionRegistry.get(/** @type {string} */ (action.tag));
        if (clientAction.target) {
            return clientAction.target;
        }
    }
    if (action.target === "fullscreen") {
        return "fullscreen";
    }
    return "current";
}
