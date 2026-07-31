// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/reports/utils */

import { download } from "@web/core/network/download";

/** @import { Context, ReportAction } from "../action_service.js" */

/**
 * @param {ReportAction} action
 * @param {string} type
 * @param {Context} [userContext] only read for the "html" type
 * @returns {string}
 */
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
 * @param {ReportAction} action
 * @param {"pdf"|"text"} type
 * @param {Context} userContext
 * @returns {Promise<void>}
 */
export async function downloadReport(action, type, userContext) {
    const url = getReportUrl(action, type);
    await download({
        url: "/report/download",
        data: {
            data: JSON.stringify([url, action.report_type]),
            context: JSON.stringify(userContext),
        },
    });
}
