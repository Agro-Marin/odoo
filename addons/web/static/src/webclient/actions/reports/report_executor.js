// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/reports/report_executor - Executes ir.actions.report as HTML preview or PDF/text download */

/**
 * Report action executor functions for the action service.
 *
 * Handles execution of ir.actions.report actions, including HTML previews
 * (via ReportAction client component) and PDF/text downloads.
 */

import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";

// Pre-execution hooks for ir.actions.report. Each handler is called with
// `(action, options, env)`; returning a truthy value short-circuits the
// default report flow (used by IoT and POS to redirect printing).
registry
    .category("ir.actions.report handlers")
    .addValidation((entry) => typeof entry === "function");
import { user } from "@web/services/user";

import { ReportAction } from "./report_action.js";
import { downloadReport, getReportUrl } from "./utils.js";

/** @import { ActionManager } from "../action_service.js" */
/** @import { ReportAction as ReportActionType } from "@web/webclient/actions/action_service" */

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
            const { onClose } = options;
            if (action.close_on_report_download) {
                return am.doAction(
                    { type: "ir.actions.act_window_close" },
                    { onClose },
                );
            } else if (onClose) {
                onClose();
            }
            return result;
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
            // WeasyPrint always produces the file or throws; there is no
            // wkhtmltopdf fallback to fall back onto, so downloadReport resolves
            // with nothing on success and rejects (surfaced by the error
            // service) on failure.
            await downloadReport(rpc, action, type, downloadContext);
        } finally {
            am.env.services.ui.unblock();
        }
        const { onClose } = options;
        if (action.close_on_report_download) {
            return am.doAction({ type: "ir.actions.act_window_close" }, { onClose });
        } else if (onClose) {
            onClose();
        }
    } else {
        console.error(
            `The ActionManager can't handle reports of type ${action.report_type}`,
            action,
        );
    }
}
