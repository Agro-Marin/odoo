// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_executors/act_window - Executor for ir.actions.act_window */

import { omit, pick } from "@web/core/utils/collections/objects";
import { View } from "@web/views/view";

import { buildActionViews } from "../action_info_builders.js";
import { findView } from "../action_views.js";

/** @import { ActionManager, ActionOptions, ActWindowAction } from "../action_service.js" */

/**
 * Settle the "lazy" trailing crumb a URL restore leaves behind.
 *
 * ``controllersFromState`` marks the last reconstructed controller ``lazy``
 * when the URL points at a record: it stands for the multi-record view the
 * record was opened FROM, which was never loaded. Now that the action is
 * known, that placeholder either becomes a real crumb (the action does have a
 * multi-record view to promote it into) or is dropped (it does not).
 *
 * Returns fresh ``options``/``newStack``/controller objects rather than
 * editing them in place. ``doAction``'s shallow copy of ``options`` reads as
 * isolation but gives none one level down, and an executor gets to PROPOSE a
 * stack, not to rewrite its caller's.
 *
 * @param {ActWindowAction} action
 * @param {ActionOptions} options
 * @returns {ActionOptions} ``options`` unchanged when there is no lazy crumb
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
 * Execute an action of type ``ir.actions.act_window``: resolve the view,
 * build the controller, and render it. If ``options.newStack`` ends in a lazy
 * controller but the action has no multi-record view to promote it into, the
 * lazy crumb is dropped.
 *
 * @param {ActWindowAction} action
 * @param {ActionOptions} options the full caller options bag, forwarded
 *   verbatim by the dispatcher and passed on to ``_updateUI`` — see the note in
 *   ``act_url.js``. Narrowing it to the keys read here would reject callers
 *   passing any other legitimate option.
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
        view = findView(views, view.multiRecord, action.mobile_view_mode) || view;
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
