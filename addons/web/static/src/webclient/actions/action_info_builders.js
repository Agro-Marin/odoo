// @ts-check
/** @odoo-module native */

import { session } from "@web/session";

/**
 * @import { Action, ActWindowAction, ActionManager, ActionProps, BaseView, Config, Controller } from "./action_service.js"
 */

/**
 * `shallowEqual`'s own comparison, so the patch-vs-clone rewrite below is
 * value-for-value what the clone used to decide (`0`/`-0` equal, `NaN` equal).
 *
 * @param {any} a
 * @param {any} b
 * @returns {boolean}
 */
function sameValue(a, b) {
    return a === b || (Number.isNaN(a) && Number.isNaN(b));
}

/**
 * @param {Record<string, any>} currentState
 * @param {string|undefined} target
 * @param {ActionManager} am
 * @returns {(controller: Controller, patchState: Record<string, any>) => void}
 */
function makeActionStateUpdater(currentState, target, am) {
    return (controller, patchState) => {
        // Compare against the patch rather than cloning the state to diff it:
        // this runs on every record navigation, and the overwhelmingly common
        // patch is a no-op that used to allocate a copy to discover as much.
        // A key the state does not carry yet counts as a change even when its
        // value is `undefined`, matching the key-count arm of `shallowEqual`.
        let changed = false;
        for (const [key, value] of Object.entries(patchState)) {
            if (
                !Object.hasOwn(currentState, key) ||
                !sameValue(currentState[key], value)
            ) {
                changed = true;
            }
            currentState[key] = value;
        }
        if (changed && target !== "new" && controller.isMounted) {
            am.pushState();
        }
    };
}

/**
 * The two builders below agree on what an action's state and name are; only
 * where `resId` comes from differs.
 *
 * @param {Action} action
 * @param {ActionProps} props mutated: gains `updateActionState`
 * @param {any} resId
 * @param {ActionManager} am
 * @returns {Record<string, any>} the live `currentState` the updater patches
 */
function attachActionState(action, props, resId, am) {
    const currentState = { resId, active_id: action.context?.active_id };
    props.updateActionState = makeActionStateUpdater(currentState, action.target, am);
    return currentState;
}

/**
 * @param {Action} action
 * @returns {string}
 */
function actionDisplayName(action) {
    return action.display_name || action.name || "";
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
    const currentState = attachActionState(
        action,
        actionProps,
        actionProps.resId ?? false,
        am,
    );
    return {
        props: actionProps,
        currentState,
        config: {
            actionId: action.id,
            actionType: "ir.actions.client",
        },
        displayName: actionDisplayName(action),
    };
}

/**
 * @param {BaseView} view
 * @param {BaseView[]} views
 * @returns {Record<string, any>[]}
 */
function buildViewSwitcherEntries(view, views) {
    return views
        .filter((v) => v.multiRecord === view.multiRecord)
        .map((v) => {
            /** @type {Record<string, any>} */
            const entry = {
                icon: v.icon,
                name: v.display_name,
                type: v.type,
                multiRecord: v.multiRecord,
            };
            if (view.type === v.type) {
                entry.active = true;
            }
            return entry;
        });
}

/**
 * @param {ActWindowAction} action
 * @param {string|undefined} target
 * @param {ActionManager} am
 * @returns {(resId: any, options?: Record<string, any>) => any}
 */
function makeFormViewOpener(action, target, am) {
    return (resId, { activeIds, readonly, force, newWindow } = {}) => {
        if (target === "new") {
            return undefined;
        }
        if (am.getView("form")) {
            return am.switchView(
                "form",
                { readonly, resId, resIds: activeIds },
                { newWindow },
            );
        }
        if (force || !resId) {
            return am.doAction(
                {
                    type: "ir.actions.act_window",
                    res_model: action.res_model,
                    views: [[false, "form"]],
                },
                { newWindow, props: { readonly, resId, resIds: activeIds } },
            );
        }
        return undefined;
    };
}

/**
 * @param {ActionProps} viewProps
 * @param {ActWindowAction} action
 * @param {Record<string, any>} context
 */
function applyActionOverrides(viewProps, action, context) {
    if ("help" in action) {
        viewProps.noContentHelp = action.help;
    }
    for (const key of ["useSampleModel", "limit", "count"]) {
        if (key in action) {
            viewProps[key] = /** @type {Record<string, any>} */ (action)[key];
        }
    }
    if (context.search_disable_custom_filters) {
        viewProps.activateFavorite = false;
    }
    if (!viewProps.resId) {
        viewProps.resId = action.res_id ?? false;
    }
}

/**
 * @param {BaseView} view
 * @param {ActWindowAction} action
 * @param {Record<string, any>} context
 * @param {Record<string, any>[]} viewSwitcherEntries
 * @returns {Config}
 */
function buildViewConfig(view, action, context, viewSwitcherEntries) {
    const isForm = view.type === "form";
    return {
        actionId: action.id,
        actionName: action.name,
        cache: action.cache,
        actionType: "ir.actions.act_window",
        actionXmlId: action.xml_id,
        embeddedActions: isForm
            ? []
            : context.parent_action_embedded_actions || action.embedded_action_ids,
        parentActionId: (!isForm && context.parent_action_id) || false,
        currentEmbeddedActionId: context.current_embedded_action_id || false,
        views: action.views,
        viewSwitcherEntries,
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
export function buildViewInfo(view, action, views, props, am) {
    props = props || {};
    const target = action.target;
    const viewSwitcherEntries = buildViewSwitcherEntries(view, views);
    const context = action.context || {};
    let groupBy = context.group_by || [];
    if (typeof groupBy === "string") {
        groupBy = groupBy ? [groupBy] : [];
    }
    const openFormView = makeFormViewOpener(action, target, am);
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
    if (view.type === "form" && target === "new") {
        viewProps.readonly = false;
        viewProps.onSave ??= (/** @type {any} */ record, /** @type {any} */ params) => {
            if (params?.closable) {
                am.doAction({ type: "ir.actions.act_window_close" });
            }
        };
    }

    applyActionOverrides(viewProps, action, context);

    const currentState = attachActionState(action, viewProps, viewProps.resId, am);

    viewProps.noBreadcrumbs =
        "_noBreadcrumbs" in action ? action._noBreadcrumbs : target === "new";

    return {
        props: viewProps,
        currentState,
        config: buildViewConfig(view, action, context, viewSwitcherEntries),
        displayName: actionDisplayName(action),
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
