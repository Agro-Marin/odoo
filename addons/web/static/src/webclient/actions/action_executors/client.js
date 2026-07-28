// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_executors/client - Executor for ir.actions.client */

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { pick } from "@web/core/utils/collections/objects";

import { nextActionDepth } from "../action_constants.js";

const actionRegistry = registry.category("actions");

/** @import { ActionManager, ActionOptions, ClientAction } from "../action_service.js" */

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
 * @param {ActionOptions} options the full caller options bag. Same reason as
 *   ``act_url.js``: the dispatcher in ``action_service`` forwards it verbatim to
 *   every executor, and this executor spreads it into the follow-up
 *   ``doAction``, so narrowing it to the keys read here made callers passing any
 *   other legitimate option (``onClose``, ``clearBreadcrumbs``, …) a type error.
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
            // The obligation moves along with the chain rather than being
            // settled here and again by whatever the follow-up resolves to.
            const depth = nextActionDepth(options);
            return am.doAction(next, { ...options, _actionDepth: depth });
        }
        // A function client action is a one-shot side effect: it is finished
        // the moment it returns, so it owes the caller the ``onClose`` an
        // ``act_window_close`` in its place would have settled. Without it a
        // view button whose method wrote something and returned
        // ``display_notification`` never reloaded its view, while the SAME
        // method returning nothing did — that answer becomes an
        // ``act_window_close``, and ``view_button_hook`` reloads off its
        // ``onClose``.
        options.onClose?.();
    }
}
