// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/reports/report_executor - Executes ir.actions.report as HTML preview or PDF/text download */

import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { user } from "@web/services/user";

import { ReportAction } from "./report_action.js";
import { downloadReport, getReportUrl } from "./utils.js";

registry
    .category("ir.actions.report handlers")
    .addValidation((entry) => typeof entry === "function");

/** @import { ActionManager, ReportAction as ReportActionType } from "../action_service.js" */

/**
 * Execute a report action as a client-side HTML preview.
 *
 * @param {ReportActionType} action the report action descriptor
 * @param {Object} options action execution options
 * @param {ActionManager} am
 * @returns {Promise}
 */
export function executeReportClientAction(action, options, am) {
    const props = {
        ...options.props,
        data: action.data,
        display_name: action.display_name,
        name: action.name,
        report_file: action.report_file,
        report_name: action.report_name,
        report_url: getReportUrl(action, "html", user.context),
        context: { ...action.context },
    };

    const controller = am._makeController({
        Component: ReportAction,
        action,
        ...am._getActionInfo(action, props),
    });

    return am._updateUI(controller, options);
}

/**
 * Settle the dialog (if any) the report was launched from.
 *
 * Both terminal paths of {@link executeReportAction} — a registry handler
 * claiming the report, and the built-in PDF/text download — owe the caller the
 * same thing once the document has been produced.
 *
 * @param {ReportActionType} action
 * @param {Object} options
 * @param {ActionManager} am
 * @returns {Promise|undefined} the close action's promise when one is
 *   dispatched, so callers can keep propagating it as the action's result
 *   exactly as both copies did
 */
function finishReport(action, options, am) {
    const { onClose } = options;
    if (action.close_on_report_download) {
        return am.doAction({ type: "ir.actions.act_window_close" }, { onClose });
    }
    onClose?.();
    return undefined;
}

/**
 * Execute a report action. Delegates to registered report handlers first,
 * then falls back to HTML preview or PDF/text download.
 *
 * @param {ReportActionType} action the report action descriptor
 * @param {Object} options action execution options
 * @param {ActionManager} am
 * @returns {Promise}
 */
export async function executeReportAction(action, options, am) {
    const handlers = registry.category("ir.actions.report handlers").getAll();
    for (const handler of handlers) {
        const result = await handler(action, options, am.env);
        if (result) {
            return finishReport(action, options, am) ?? result;
        }
    }
    if (action.report_type === "qweb-html") {
        return executeReportClientAction(action, options, am);
    } else if (
        action.report_type === "qweb-pdf" ||
        action.report_type === "qweb-text"
    ) {
        const type = action.report_type === "qweb-pdf" ? "pdf" : "text";
        am.env.services.ui.block();
        try {
            const downloadContext = { ...user.context };
            if (action.context) {
                Object.assign(downloadContext, action.context);
            }
            await downloadReport(rpc, action, type, downloadContext);
        } finally {
            am.env.services.ui.unblock();
        }
        return finishReport(action, options, am);
    } else {
        // SINGLE EXIT — ``options.onClose`` runs on every path, the same rule
        // ``act_url.js`` spells out. Nothing was produced, but the caller is
        // still waiting: this is how ``view_button_hook`` reloads its view and
        // how ``doAction(..., { onClose: resolve })`` awaits an action. A
        // report whose type no LOADED handler claims (an enterprise handler
        // missing from the bundle) takes this path, and returning without
        // settling stranded the caller rather than doing less.
        console.error(
            `The ActionManager can't handle reports of type ${action.report_type}`,
            action,
        );
        options.onClose?.();
    }
}
