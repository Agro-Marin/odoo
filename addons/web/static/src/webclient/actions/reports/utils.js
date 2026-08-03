// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/reports/utils */

import { download } from "@web/core/network/download";

/** @import { Context, ReportAction } from "../action_service.js" */

/**
 * The context a report renders under: the user's, with the action's on top.
 * `preprocessAction` does not fold `user.context` into `action.context` — the
 * former is only the evaluation context — so neither one alone is the answer.
 *
 * @param {ReportAction} action
 * @param {Context} [userContext]
 * @returns {Context}
 */
export function getReportContext(action, userContext) {
    return { ...userContext, ...(action.context || {}) };
}

/**
 * @param {ReportAction} action
 * @param {string} type
 * @param {Context} [userContext]
 * @returns {string}
 */
export function getReportUrl(action, type, userContext) {
    let url = `/report/${type}/${action.report_name}`;
    const renderContext = getReportContext(action, userContext);
    const context = encodeURIComponent(JSON.stringify(renderContext));
    if (action.data && JSON.stringify(action.data) !== "{}") {
        const options = encodeURIComponent(JSON.stringify(action.data));
        url += `?options=${options}&context=${context}`;
    } else {
        if (renderContext.active_ids) {
            url += `/${renderContext.active_ids.join(",")}`;
        }
        if (type === "html") {
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
    const renderContext = getReportContext(action, userContext);
    const url = getReportUrl(action, type, userContext);
    await download({
        url: "/report/download",
        data: {
            data: JSON.stringify([url, action.report_type]),
            context: JSON.stringify(renderContext),
        },
    });
}
