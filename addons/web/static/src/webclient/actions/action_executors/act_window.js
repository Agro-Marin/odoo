// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_executors/act_window - Executor for ir.actions.act_window */

import { pick } from "@web/core/utils/collections/objects";
import { View } from "@web/views/view";

import { clearUncommittedChanges } from "../action_clear_changes.js";
import { buildActionViews } from "../action_info_builders.js";
import { findView } from "../action_views.js";

/** @import { ActionManager } from "../action_service.js" */
/** @import { ActWindowAction } from "@web/webclient/actions/action_service" */

/**
 * Execute an action of type ``ir.actions.act_window``: resolve the view,
 * build the controller, and render it. If ``options.newStack`` ends in a lazy
 * controller but the action has no multi-record view to promote it into, the
 * lazy crumb is dropped.
 *
 * @param {ActWindowAction} action
 * @param {{
 *   viewType?: string,
 *   newWindow?: boolean,
 *   newStack?: object[],
 *   props?: object,
 *   forceLeave?: boolean,
 * }} options
 * @param {ActionManager} am
 */
export async function executeActWindowAction(action, options, am) {
    if (action.target !== "new" && !options.newWindow) {
        const canProceed = await clearUncommittedChanges(
            am.env,
            pick(options, "forceLeave"),
        );
        if (!canProceed) {
            return;
        }
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
    // preprocessAction always seeds `controllers` to {}, but the raw
    // ActWindowAction type marks it optional; ??= satisfies the type while
    // staying a no-op on the always-present runtime value.
    (action.controllers ??= {})[view.type] = controller;

    const newStackLastController = options.newStack?.at(-1);
    if (newStackLastController?.lazy) {
        const multiView = action.views.find(
            (view) => view[1] !== "form" && view[1] !== "search",
        );
        if (multiView) {
            // The action has a multi-record view; keep the lazy crumb and
            // promote it into a real breadcrumb pointing at that view.
            delete newStackLastController.lazy;
            newStackLastController.displayName =
                action.display_name || action.name || "";
            newStackLastController.action = action;
            newStackLastController.props.type = multiView[1];
        } else {
            // No multi-record view — drop the lazy crumb entirely.
            // newStack is guaranteed here (newStackLastController came from
            // its last element); ?. satisfies strictNullChecks.
            options.newStack?.splice(-1);
        }
    }
    return am._updateUI(controller, options);
}
