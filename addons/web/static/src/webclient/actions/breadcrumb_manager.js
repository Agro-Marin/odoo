// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/breadcrumb_manager */

import { rpc } from "@web/core/network/rpc";
import { zip } from "@web/core/utils/collections/arrays";
import { pick } from "@web/core/utils/collections/objects";

import { resolveClientAction } from "./action_loader.js";
import { actionStorage } from "./action_storage.js";

/** @import { ActionManager, Controller } from "./action_service.js" */

/**
 * @param {{ tag?: any, id?: any }} [action]
 * @returns {boolean}
 */
export function isMenuController(action) {
    return action?.tag === "menu" || action?.id === "menu";
}

/**
 * @param {Record<string, any>[]} toFetch
 * @param {import("./breadcrumb_cache.js").BreadcrumbCache} breadcrumbCache
 */
function fetchBreadcrumbs(toFetch, breadcrumbCache) {
    const req = rpc("/web/action/load_breadcrumbs", { actions: toFetch }, { retry: 1 });
    for (const [i, info] of toFetch.entries()) {
        const key = JSON.stringify(info);
        breadcrumbCache.set(
            key,
            req.then(
                (res) => {
                    if (res[i] && "display_name" in res[i]) {
                        breadcrumbCache.set(key, res[i]);
                    } else {
                        breadcrumbCache.delete(key);
                    }
                    return res[i];
                },
                (error) => {
                    breadcrumbCache.delete(key);
                    throw error;
                },
            ),
        );
    }
}

/**
 * What identifies a crumb to the server, and the cache key that stands for it.
 *
 * @param {Controller} controller
 * @returns {{ key: string, actionInfo: Record<string, any> }}
 */
function breadcrumbKey(controller) {
    const actionInfo = pick(
        /** @type {Record<string, any>} */ (controller.state),
        "action",
        "model",
        "resId",
    );
    return { actionInfo, key: JSON.stringify(actionInfo) };
}

/**
 * @typedef {{ controller: Controller, key: string, actionInfo: Record<string, any> }} BreadcrumbEntry
 */

/**
 * Ask the server for whatever `entries` the cache cannot answer, then settle
 * every entry against it, in order. One round-trip for the lot: duplicates
 * within a call share a key and are asked for once.
 *
 * A rejected fetch settles as `{ error }` rather than rejecting the batch —
 * what each caller does about a crumb it could not name is its own business.
 *
 * @param {BreadcrumbEntry[]} entries
 * @param {import("./breadcrumb_cache.js").BreadcrumbCache} breadcrumbCache
 * @returns {Promise<[BreadcrumbEntry, Record<string, any>][]>}
 */
async function resolveBreadcrumbs(entries, breadcrumbCache) {
    const toFetch = [];
    const queued = new Set();
    for (const { key, actionInfo } of entries) {
        if (breadcrumbCache.has(key)) {
            breadcrumbCache.touch(key);
        } else if (!queued.has(key)) {
            queued.add(key);
            toFetch.push(actionInfo);
        }
    }
    if (toFetch.length) {
        fetchBreadcrumbs(toFetch, breadcrumbCache);
    }
    const results = await Promise.all(
        entries.map((entry) =>
            Promise.resolve(breadcrumbCache.get(entry.key)).catch((error) => ({
                error,
            })),
        ),
    );
    return zip(entries, results);
}

/**
 * One entry of the breadcrumb trail, as the control panel consumes it.
 *
 * @typedef {Object} Breadcrumb
 * @property {string} jsId
 * @property {string} [name]
 * @property {boolean} isFormView
 * @property {string} url
 * @property {() => void} onSelected
 */

/**
 * @param {Controller[]} stack
 * @param {ActionManager} am
 * @returns {Breadcrumb[]}
 */
export function buildBreadcrumbs(stack, am) {
    return stack
        .filter((controller) => !isMenuController(controller.action))
        .map((controller) => ({
            jsId: controller.jsId,
            name: controller.displayName,
            get isFormView() {
                return controller.props?.type === "form";
            },
            get url() {
                return am.router.stateToUrl(controller.state);
            },
            onSelected() {
                am.restore(controller.jsId);
            },
        }));
}

/**
 * @param {Controller[]} controllers
 * @param {import("./breadcrumb_cache.js").BreadcrumbCache} breadcrumbCache
 * @returns {Promise<Controller[]>}
 */
async function loadBreadcrumbs(controllers, breadcrumbCache) {
    const candidates = [];
    /**
     * Keys whose name the url already carried. Good enough to render THIS
     * restore without a round-trip, but not a fact about the record: it was
     * written when the crumb was last visited and the record may have been
     * renamed since. Kept per call so it cannot outlive the url that supplied
     * it — writing it into `breadcrumbCache` pinned the stale name for the rest
     * of the session, and suppressed the fetch even on later navigations whose
     * url carried no name at all.
     *
     * @type {Map<string, string>}
     */
    const namedFromUrl = new Map();
    for (const controller of controllers) {
        const { action, displayName } = controller;
        if (
            isMenuController(action) ||
            (action.type === "ir.actions.client" && !displayName)
        ) {
            continue;
        }
        const { key, actionInfo } = breadcrumbKey(controller);
        candidates.push({ controller, key, actionInfo });
        if (displayName) {
            namedFromUrl.set(key, displayName);
        }
    }

    // Second pass: a key is named if ANY controller on it was, whatever the
    // order they appear in. The one the url named lends its name to the others
    // on the same record, as they used to borrow it through the cache.
    const entries = [];
    for (const candidate of candidates) {
        const urlName = namedFromUrl.get(candidate.key);
        if (urlName !== undefined) {
            candidate.controller.displayName = urlName;
        } else {
            entries.push(candidate);
        }
    }

    const dropped = new Set();
    for (const [{ controller }, res] of await resolveBreadcrumbs(
        entries,
        breadcrumbCache,
    )) {
        if (res && "display_name" in res) {
            controller.displayName = res.display_name;
            continue;
        }
        if (res && "error" in res) {
            console.warn(
                "A breadcrumb could not be loaded and was dropped from the trail " +
                    "and from the url. The server did not answer for:\n",
                controller.state,
                "\n",
                res.error,
            );
        }
        dropped.add(controller);
    }
    return controllers.filter((c) => !dropped.has(c));
}

/**
 * @param {Controller[]} controllers
 * @param {import("./breadcrumb_cache.js").BreadcrumbCache} breadcrumbCache
 * @returns {Promise<void>}
 */
export async function refreshBreadcrumbDisplayNames(controllers, breadcrumbCache) {
    const entries = [];
    for (const controller of controllers) {
        const { action, state } = controller;
        if (!state || isMenuController(action) || action.type === "ir.actions.client") {
            continue;
        }
        entries.push({ controller, ...breadcrumbKey(controller) });
    }
    // Unlike a restore, a refresh keeps a crumb it could not name: the trail on
    // screen is already correct, and an action record changing under it is no
    // reason to take an entry out of it.
    for (const [{ controller }, res] of await resolveBreadcrumbs(
        entries,
        breadcrumbCache,
    )) {
        if (res && "display_name" in res) {
            controller.displayName = res.display_name;
        }
    }
}

/**
 * @param {Record<string, any>} state
 * @param {ActionManager} am
 * @returns {Promise<Controller[]>}
 */
export async function controllersFromState(state, am) {
    const currentState = actionStorage.getCurrentState();
    if (am.router.stateToUrl(currentState) === am.router.stateToUrl(state)) {
        state = currentState;
    }
    if (!state?.actionStack?.length) {
        return [];
    }
    const controllers = state.actionStack
        .slice(0, -1)
        .map((actionState, index) => {
            const controller = am._makeController({
                displayName: actionState.displayName,
                virtual: true,
                // Where in `state.actionStack` this crumb came from. The list
                // returned here is shorter than the actionStack whenever a
                // crumb could not be named, so a caller holding a position
                // measured on the url cannot count its way back into it.
                stackIndex: index,
                action: {},
                props: {},
                state: {
                    ...actionState,
                    actionStack: state.actionStack.slice(0, index + 1),
                },
                currentState: {},
            });
            const controllerState = /** @type {Record<string, any>} */ (
                controller.currentState
            );
            if (actionState.action) {
                controller.action.id = actionState.action;

                const [actionRequestKey, clientAction] = resolveClientAction(
                    actionState.action,
                );
                if (actionRequestKey && clientAction) {
                    if (state.actionStack[index + 1]?.action === actionState.action) {
                        return;
                    }
                    controller.action.tag = actionRequestKey;
                    controller.action.type = "ir.actions.client";
                    controller.displayName = clientAction.displayName?.toString();
                }
                if (actionState.active_id) {
                    controller.action.context = {
                        active_id: actionState.active_id,
                    };
                    controllerState.active_id = actionState.active_id;
                }
            }
            if (actionState.model) {
                controller.action.type = "ir.actions.act_window";
                controller.props.resModel = actionState.model;
            }
            if (actionState.resId) {
                controller.action.type ||= "ir.actions.act_window";
                controller.props.resId = actionState.resId;
                controllerState.resId = actionState.resId;
                controller.props.type = "form";
            }
            return controller;
        })
        .filter(Boolean);

    if (
        state.action &&
        state.resId &&
        controllers.at(-1)?.action?.id === state.action
    ) {
        const bcControllers = await loadBreadcrumbs(
            controllers.slice(0, -1),
            am.breadcrumbCache,
        );
        controllers.at(-1).lazy = true;
        return [...bcControllers, controllers.at(-1)];
    }
    return loadBreadcrumbs(controllers, am.breadcrumbCache);
}
