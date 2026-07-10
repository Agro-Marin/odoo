// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_executors/client - Executor for ir.actions.client */

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { pick } from "@web/core/utils/collections/objects";

import { clearUncommittedChanges } from "../action_clear_changes.js";

const actionRegistry = registry.category("actions");

/** @import { ActionManager } from "../action_service.js" */
/** @import { ClientAction } from "@web/webclient/actions/action_service" */

/**
 * Execute an action of type ``ir.actions.client``.
 *
 * Two branches based on the registry entry's shape:
 *   - **Component class** — build a Controller around it, render via
 *     ``am._updateUI``.  Honors ``clientAction.target`` override and
 *     ``extractProps`` factory if defined on the class.
 *   - **Plain function** — invoke as a side-effect callback that may
 *     return a follow-up action.  Guarded by a recursion depth limit
 *     (max 20) to catch action loops at the client level.
 *
 * @param {ClientAction} action
 * @param {{
 *   target?: string,
 *   newWindow?: boolean,
 *   props?: object,
 *   forceLeave?: boolean,
 *   _actionDepth?: number,
 * }} options
 * @param {ActionManager} am
 */
export async function executeClientAction(action, options, am) {
    const clientAction = actionRegistry.get(action.tag);
    action.path ||= clientAction.path;
    if (clientAction.prototype instanceof Component) {
        if (action.target !== "new" && !options.newWindow) {
            const canProceed = await clearUncommittedChanges(
                am.env,
                pick(options, "forceLeave"),
            );
            if (!canProceed) {
                return;
            }
            if (clientAction.target) {
                action.target = clientAction.target;
            }
        }
        const props = /** @type {any} */ (clientAction).extractProps?.(action) || {};
        const controller = am._makeController({
            Component: /** @type {any} */ (clientAction),
            action,
            ...am._getActionInfo(action, { ...props, ...options.props }),
        });
        controller.displayName ||= clientAction.displayName?.toString() || "";
        return am._updateUI(controller, options);
    } else {
        const next = await /** @type {any} */ (clientAction)(am.env, action, options);
        if (next) {
            const depth = (options._actionDepth || 0) + 1;
            if (depth > 20) {
                throw new Error("Action recursion limit exceeded (max 20)");
            }
            return am.doAction(next, { ...options, _actionDepth: depth });
        }
    }
}
