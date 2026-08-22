// @ts-check
/** @odoo-module native */

import { omit, pick } from "@web/core/utils/collections/objects";
import { View } from "@web/views/view";

import { buildActionViews } from "../action_info_builders.js";
import { findView } from "../action_views.js";

/** @import { ActionManager, ActionOptions, ActWindowAction } from "../action_service.js" */

/**
 * @param {ActWindowAction} action
 * @param {ActionOptions} options
 * @returns {ActionOptions}
 */
function resolveLazyCrumb(action, options) {
    const newStack = options.newStack;
    if (!newStack?.length) {
        return options;
    }
    const lastController = newStack.at(-1);
    if (!lastController?.lazy) {
        return options;
    }
    const multiView = action.views.find(
        (view) => view[1] !== "form" && view[1] !== "search",
    );
    if (!multiView) {
        return { ...options, newStack: newStack.slice(0, -1) };
    }
    return {
        ...options,
        newStack: [
            ...newStack.slice(0, -1),
            {
                ...omit(lastController, "lazy"),
                action,
                displayName: action.display_name || action.name || "",
                props: { ...lastController.props, type: multiView[1] },
            },
        ],
    };
}

/**
 * @param {ActWindowAction} action
 * @param {ActionOptions} options
 * @param {ActionManager} am
 */
export async function executeActWindowAction(action, options, am) {
    if (
        action.target !== "new" &&
        !options.newWindow &&
        !(await am._confirmLeave(pick(options, "forceLeave")))
    ) {
        return;
    }
    const views = buildActionViews(action);

    let view =
        (options.viewType && views.find((v) => v.type === options.viewType)) ||
        views[0];
    if (am.env.isSmall) {
        view =
            findView(
                views,
                /** @type {boolean} */ (view.multiRecord),
                action.mobile_view_mode,
            ) || view;
    }

    const controller = am._makeController({
        Component: View,
        action,
        view,
        views,
        ...am._getViewInfo(view, action, views, options.props),
    });
    (action.controllers ??= {})[view.type] = controller;

    return am._updateUI(controller, resolveLazyCrumb(action, options));
}
