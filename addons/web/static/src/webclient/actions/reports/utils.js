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
 * Launches download action of the report. With the WeasyPrint migration there
 * is no wkhtmltopdf fallback — download either succeeds or throws.
 *
 * @param {unknown} _rpc unused. A leftover of the wkhtmltopdf fallback, which
 *  needed an RPC to probe for the binary; the download is a plain form POST
 *  now. Kept as a positional placeholder because ``point_of_sale``'s
 *  ``report_service`` still passes it — it is NOT read, and callers may pass
 *  ``undefined``. Underscore-prefixed so a reader does not go looking for the
 *  use.
 * @param {Object} action the report action
 * @param {"pdf"|"text"} type the type of the report to download
 * @param {Object} userContext the user context, sent alongside the download —
 *  deliberately not forwarded to {@link getReportUrl}, which only consults a
 *  user context for ``html`` reports and never sees one here.
 * @returns {Promise<void>}
 */
export async function downloadReport(_rpc, action, type, userContext) {
    const url = getReportUrl(action, type);
    await download({
        url: "/report/download",
        data: {
            data: JSON.stringify([url, action.report_type]),
            context: JSON.stringify(userContext),
        },
    });
}
