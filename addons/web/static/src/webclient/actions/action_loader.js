// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_loader - Load, normalize, and wrap action descriptions and controllers for the action service */

import { markup } from "@odoo/owl";
import { makeContext } from "@web/core/context";
import { rpc } from "@web/core/network/rpc";
import { evaluateExpr } from "@web/core/py_js/py";
import { registry } from "@web/core/registry";
import { isHtmlEmpty } from "@web/core/utils/dom/html";
import { user } from "@web/services/user";

const actionRegistry = registry.category("actions");

/** @import { ActionManager } from "./action_service.js" */
/** @import { Action } from "@web/webclient/actions/action_service" */

/**
 * Given an id, xmlid, tag (key of the client action registry), or directly
 * an object describing an action, return the action description.
 *
 * Fetched via `/web/action/load` with disk-cache and one retry: actions are
 * read-only (cache invalidated explicitly on write/unlink) and cold-cache
 * failures break navigation page-wide, so retry is safe.
 *
 * DEFERRED — stale-while-revalidate (``update: "always"`` + an ``onRevalidate``
 * callback refreshing the on-screen controller) would close the cross-session
 * staleness gap (an admin editing an action's domain/context currently leaves
 * every OTHER user on the IndexedDB-cached descriptor across reloads until they
 * themselves write ``ir.actions``). It was implemented and reverted here: with
 * ``update: "always"`` every warm read fires a background ``/web/action/load``,
 * which the action test-suite's ~50 exact-RPC-sequence and Deferred-mocked
 * ``/web/action/load`` tests pin against — the change cascaded into a suite-wide
 * hang. A viable version needs a server-side freshness signal (action etag /
 * ``registry_hash``-style version) so revalidation is conditional rather than
 * unconditional-per-navigation; tracked as a separate task.
 *
 * @param {number | string | object} actionRequest
 * @param {object} [context]
 * @returns {Promise<Action>}
 */
export async function loadAction(actionRequest, context = {}) {
    if (typeof actionRequest === "string" && actionRegistry.contains(actionRequest)) {
        // actionRequest is a key in the actionRegistry
        return {
            target: "current",
            tag: actionRequest,
            type: "ir.actions.client",
        };
    }

    if (typeof actionRequest === "string" || typeof actionRequest === "number") {
        // actionRequest is an id or an xmlid
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

    // actionRequest is an object describing the action. The caller is
    // trusted to pass a well-formed action descriptor here (server-loaded
    // or hand-built); narrow the `object` param to the Action union.
    return /** @type {Action} */ (actionRequest);
}

/**
 * Wrap a parameter bag into a Controller record with a unique `jsId`.
 *
 * @param {object} params
 * @param {ActionManager} am
 * @returns {object} the new controller
 */
export function makeController(params, am) {
    return {
        ...params,
        jsId: `controller_${am._nextId()}`,
        isMounted: false,
    };
}

/**
 * Normalize an action description into the canonical form expected by the
 * rest of the action service:
 *
 *   - serialize the original action into `_originalAction` (for restore-from-URL)
 *   - merge contexts (caller + action.context + user.context)
 *   - evaluate the domain expression if it's a string
 *   - drop `help` when its HTML is empty
 *   - stamp a unique `jsId` (`action_<n>`)
 *   - default `target` to "current" for window / client actions
 *   - for `ir.actions.act_window`: split form-vs-search views, prepare a
 *     `controllers` map, and extract `no_breadcrumbs` from context
 *
 * Returns a fresh object so the cached action descriptor remains unmodified.
 *
 * @param {Action} action - mutable action descriptor
 * @param {object} context - additional caller context to merge
 * @param {ActionManager} am
 * @returns {Action} the normalized action (a fresh copy)
 */
export function preprocessAction(action, context, am) {
    action = { ...action }; // manipulate a copy to keep cached action unmodified
    try {
        delete action._originalAction;
        action._originalAction = JSON.stringify(action);
    } catch {
        // do nothing, the action might not be serializable
    }
    action.context = makeContext([context, action.context], user.context);
    const domain = action.domain || [];
    action.domain =
        typeof domain === "string"
            ? evaluateExpr(domain, { ...user.context, ...action.context })
            : domain;
    if (action.help) {
        if (isHtmlEmpty(action.help)) {
            delete action.help;
        }
    }
    action.jsId = `action_${am._nextId()}`;
    if (
        action.type === "ir.actions.act_window" ||
        action.type === "ir.actions.client"
    ) {
        action.target = action.target || "current";
    }
    if (action.type === "ir.actions.act_window") {
        // The inner [id, type] literal is a tuple, not a loose array; the
        // cast keeps the [number|false, string][] element type through .map.
        action.views = action.views.map(
            (v) => /** @type {[number | false, string]} */ ([v[0], v[1]]),
        ); // copy
        action.controllers = {};
        if (action.views.every((v) => ["form", "search"].includes(v[1]))) {
            action.views = action.views.filter((v) => v[1] === "form");
        } else {
            const searchViewId = action.search_view_id
                ? action.search_view_id[0]
                : false;
            action.views.push([searchViewId, "search"]);
        }
        if (action.context && "no_breadcrumbs" in action.context) {
            action._noBreadcrumbs = action.context.no_breadcrumbs;
            delete action.context.no_breadcrumbs;
        }
    }
    return action;
}
