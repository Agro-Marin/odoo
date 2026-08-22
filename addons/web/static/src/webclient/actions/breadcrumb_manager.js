// @ts-check
/** @odoo-module native */

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
