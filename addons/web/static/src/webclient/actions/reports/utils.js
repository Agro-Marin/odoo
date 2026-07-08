// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/reports/utils - Report URL generation and download helper for ir.actions.report */

/**
 * Generates the report url given a report action.
 *
 * @param {Object} action the report action
 * @param {string} type the type of the report
 * @param {Object} userContext the user context
 * @returns {string}
 */

import { download } from "@web/core/network/download";
export function getReportUrl(action, type, userContext) {
    let url = `/report/${type}/${action.report_name}`;
    const actionContext = action.context || {};
    if (action.data && JSON.stringify(action.data) !== "{}") {
        // build a query string with `action.data` (it's the place where reports
        // using a wizard to customize the output traditionally put their options)
        const options = encodeURIComponent(JSON.stringify(action.data));
        const context = encodeURIComponent(JSON.stringify(actionContext));
        url += `?options=${options}&context=${context}`;
    } else {
        if (actionContext.active_ids) {
            url += `/${actionContext.active_ids.join(",")}`;
        }
        if (type === "html") {
            const context = encodeURIComponent(JSON.stringify(userContext));
            url += `?context=${context}`;
        }
    }
    return url;
}

/**
 * Launches download action of the report.
 *
 * With the WeasyPrint migration there is no longer a wkhtmltopdf fallback, so
 * the download either succeeds or throws — there is nothing to report back to
 * the caller and no HTML-preview fallback to trigger.
 *
 * The leading ``rpc`` parameter is unused (the download goes through the
 * ``download`` helper, not an RPC). It is retained only so the point_of_sale
 * ``report_service`` caller keeps working without changes; new callers may pass
 * ``undefined``.
 *
 * @param {Function} rpc unused — kept for positional back-compat (see above)
 * @param {Object} action the report action
 * @param {"pdf"|"text"} type the type of the report to download
 * @param {Object} userContext the user context
 * @returns {Promise<void>}
 */
export async function downloadReport(rpc, action, type, userContext) {
    const url = getReportUrl(action, type);
    await download({
        url: "/report/download",
        data: {
            data: JSON.stringify([url, action.report_type]),
            context: JSON.stringify(userContext),
        },
    });
}
