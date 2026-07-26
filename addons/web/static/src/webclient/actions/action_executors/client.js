// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_executors/client - Executor for ir.actions.client */

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { pick } from "@web/core/utils/collections/objects";

import { nextActionDepth } from "../action_constants.js";

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
 *     return a follow-up action.  Guarded by the shared
 *     ``nextActionDepth`` limit to catch action loops at the client level.
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
            if (!(await am._confirmLeave(pick(options, "forceLeave")))) {
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
            const depth = nextActionDepth(options);
            return am.doAction(next, { ...options, _actionDepth: depth });
        }
    }
}
