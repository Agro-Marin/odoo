// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_info_builders */

import { shallowEqual } from "@web/core/utils/collections/objects";
import { session } from "@web/session";

/** @import { Action, ActWindowAction, ActionManager, ActionProps, BaseView, Config, Controller } from "./action_service.js" */

/**
 * @param {Record<string, any>} currentState
 * @param {string|undefined} target
 * @param {ActionManager} am
 * @returns {(controller: Controller, patchState: Record<string, any>) => void}
 */
function makeActionStateUpdater(currentState, target, am) {
    return (controller, patchState) => {
        const oldState = { ...currentState };
        Object.assign(currentState, patchState);
        const changed = !shallowEqual(currentState, oldState);
        if (changed && target !== "new" && controller.isMounted) {
            am.pushState();
        }
    };
}

/**
 * @param {Action} action
 * @param {ActionProps} props
 * @param {ActionManager} am
 * @returns {{ props: ActionProps, currentState: Record<string, any>, config: Config, displayName: string }}
 */
export function buildActionInfo(action, props, am) {
    /** @type {ActionProps} */
    const actionProps = { ...props, action, actionId: action.id };
    const currentState = {
        resId: actionProps.resId ?? false,
        active_id: action.context?.active_id,
    };
    actionProps.updateActionState = makeActionStateUpdater(
        currentState,
        action.target,
        am,
    );
    return {
        props: actionProps,
        currentState,
        config: {
            actionId: action.id,
            actionType: "ir.actions.client",
        },
        displayName: action.display_name || action.name || "",
    };
}

/**
 * @param {BaseView} view
 * @param {ActWindowAction} action
 * @param {BaseView[]} views
 * @param {ActionProps} props
 * @param {ActionManager} am
 * @returns {{ props: ActionProps, currentState: Record<string, any>, config: Config, displayName: string }}
 */
export function buildViewInfo(view, action, views, props = {}, am) {
    const target = action.target;
    const viewSwitcherEntries = views
        .filter((v) => v.multiRecord === view.multiRecord)
        .map((v) => {
            /** @type {Record<string, any>} */
            const viewSwitcherEntry = {
                icon: v.icon,
                name: v.display_name,
                type: v.type,
                multiRecord: v.multiRecord,
            };
            if (view.type === v.type) {
                viewSwitcherEntry.active = true;
            }
            return viewSwitcherEntry;
        });
    const context = action.context || {};
    let groupBy = context.group_by || [];
    if (typeof groupBy === "string") {
        groupBy = groupBy ? [groupBy] : [];
    }
    const openFormView = (
        /** @type {any} */ resId,
        { activeIds, readonly, force, newWindow } = /** @type {any} */ ({}),
    ) => {
        if (target !== "new") {
            if (am._getView("form")) {
                return am.switchView(
                    "form",
                    { readonly, resId, resIds: activeIds },
                    { newWindow },
                );
            } else if (force || !resId) {
                return am.doAction(
                    {
                        type: "ir.actions.act_window",
                        res_model: action.res_model,
                        views: [[false, "form"]],
                    },
                    {
                        newWindow,
                        props: { readonly, resId, resIds: activeIds },
                    },
                );
            }
        }
    };
    /** @type {ActionProps} */
    const viewProps = {
        ...props,
        context,
        display: { mode: target === "new" ? "inDialog" : target },
        domain: action.domain || [],
        groupBy,
        loadActionMenus: target !== "new" && action.res_model !== "res.config.settings",
        loadIrFilters: action.views.some((v) => v[1] === "search"),
        resModel: action.res_model,
        type: view.type,
        selectRecord: openFormView,
        createRecord: () => openFormView(false),
    };
    if (view.type === "form") {
        if (target === "new") {
            viewProps.readonly = false;
            if (!viewProps.onSave) {
                viewProps.onSave = (
                    /** @type {any} */ record,
                    /** @type {any} */ params,
                ) => {
                    if (params?.closable) {
                        am.doAction({ type: "ir.actions.act_window_close" });
                    }
                };
            }
        }
    }

    const specialKeys = ["help", "useSampleModel", "limit", "count"];
    for (const key of specialKeys) {
        if (key in action) {
            if (key === "help") {
                viewProps.noContentHelp = action.help;
            } else {
                viewProps[key] = /** @type {Record<string, any>} */ (action)[key];
            }
        }
    }

    if (context.search_disable_custom_filters) {
        viewProps.activateFavorite = false;
    }

    if (!viewProps.resId) {
        viewProps.resId = action.res_id ?? false;
    }

    const currentState = {
        resId: viewProps.resId,
        active_id: action.context?.active_id,
    };
    viewProps.updateActionState = makeActionStateUpdater(currentState, target, am);

    viewProps.noBreadcrumbs =
        "_noBreadcrumbs" in action ? action._noBreadcrumbs : target === "new";

    const embeddedActions =
        view.type === "form"
            ? []
            : context.parent_action_embedded_actions || action.embedded_action_ids;
    const parentActionId = (view.type !== "form" && context.parent_action_id) || false;
    const currentEmbeddedActionId = context.current_embedded_action_id || false;
    return {
        props: viewProps,
        currentState,
        config: {
            actionId: action.id,
            actionName: action.name,
            cache: action.cache,
            actionType: "ir.actions.act_window",
            actionXmlId: action.xml_id,
            embeddedActions,
            parentActionId,
            currentEmbeddedActionId,
            views: action.views,
            viewSwitcherEntries,
        },
        displayName: action.display_name || action.name || "",
    };
}

/**
 * @param {ActWindowAction} action
 * @returns {BaseView[]}
 * @throws {Error}
 */
export function buildActionViews(action) {
    const views = [];
    const unknown = [];
    for (const [, type] of action.views) {
        if (type === "search") {
            continue;
        }
        if (session.view_info[type]) {
            const {
                icon,
                display_name,
                multi_record: multiRecord,
            } = session.view_info[type];
            views.push({ icon, display_name, multiRecord, type });
        } else {
            unknown.push(type);
        }
    }
    if (unknown.length) {
        throw new Error(
            `View types not defined ${unknown.join(", ")} found in act_window action ${action.id}`,
        );
    }
    if (!views.length) {
        throw new Error(`No view found for act_window action ${action.id}`);
    }
    return views;
}
