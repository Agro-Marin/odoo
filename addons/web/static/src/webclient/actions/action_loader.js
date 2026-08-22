// @ts-check
/** @odoo-module native */

import { markup } from "@odoo/owl";
import { makeContext } from "@web/core/context";
import { rpc } from "@web/core/network/rpc";
import { evaluateExpr } from "@web/core/py_js/py";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { isHtmlEmpty } from "@web/core/utils/dom/html";

const actionRegistry = registry.category("actions");

/**
 * @import { Action, ActionDescription, ActionManager, ActionRequest, Context, Controller } from "./action_service.js"
 */

/**
 * @param {string | number} key
 * @returns {[string, import("registries").ActionsRegistryItemShape] | []}
 */
export function resolveClientAction(key) {
    const registryKey = String(key);
    if (actionRegistry.contains(registryKey)) {
        return [registryKey, actionRegistry.get(registryKey)];
    }
    return actionRegistry.getEntries().find((entry) => entry[1].path === key) ?? [];
}

/**
 * @param {ActionRequest} actionRequest
 * @param {Context} [context]
 * @returns {Promise<Action>}
 */
export async function loadAction(actionRequest, context = {}) {
    if (typeof actionRequest === "string" && actionRegistry.contains(actionRequest)) {
        return {
            target: "current",
            tag: actionRequest,
            type: "ir.actions.client",
        };
    }

    if (typeof actionRequest === "string" || typeof actionRequest === "number") {
        const ctx = makeContext([user.context, context]);
        delete ctx.params;
        const action = await rpc(
            "/web/action/load",
            {
                action_id: actionRequest,
                context: ctx,
            },
            { cache: { type: "disk" }, retry: 1 },
        );
        if (action.help) {
            action.help = markup(action.help);
        }
        return { ...action };
    }

    return /** @type {Action} */ (actionRequest);
}

/**
 * @param {Partial<Controller> & Record<string, any>} params
 * @param {ActionManager} am
 * @returns {Controller & Record<string, any>}
 */
export function makeController(params, am) {
    return /** @type {Controller & Record<string, any>} */ ({
        ...params,
        jsId: `controller_${am._nextId()}`,
        isMounted: false,
    });
}

/**
 * @param {ActionDescription} action
 * @param {Context} context
 * @param {ActionManager} am
 * @returns {Action}
 */
export function preprocessAction(action, context, am) {
    action = /** @type {Action} */ ({ ...action });
    try {
        delete action._originalAction;
        action._originalAction = JSON.stringify(action);
    } catch {}
    action.context = makeContext([context, action.context], user.context);
    const domain = action.domain || [];
    action.domain =
        typeof domain === "string"
            ? evaluateExpr(domain, { ...user.context, ...action.context })
            : domain;
    if (action.help && isHtmlEmpty(action.help)) {
        delete action.help;
    }
    action.jsId = `action_${am._nextId()}`;
    if (
        action.type === "ir.actions.act_window" ||
        action.type === "ir.actions.client"
    ) {
        action.target = action.target || "current";
    }
    if (action.type === "ir.actions.act_window") {
        action.views = action.views.map(
            (v) => /** @type {[number | false, string]} */ ([v[0], v[1]]),
        );
        action.controllers = {};
        if (action.views.every((v) => ["form", "search"].includes(v[1]))) {
            action.views = action.views.filter((v) => v[1] === "form");
        } else {
            const searchViewId = action.search_view_id
                ? action.search_view_id[0]
                : false;
            const [declaredSearch] = action.views.filter((v) => v[1] === "search");
            if (!declaredSearch) {
                action.views.push([searchViewId, "search"]);
            } else {
                if (action.search_view_id) {
                    declaredSearch[0] = searchViewId;
                }
                action.views = action.views.filter(
                    (v) => v[1] !== "search" || v === declaredSearch,
                );
            }
        }
        if (action.context && "no_breadcrumbs" in action.context) {
            action._noBreadcrumbs = action.context.no_breadcrumbs;
            delete action.context.no_breadcrumbs;
        }
    }
    return action;
}
