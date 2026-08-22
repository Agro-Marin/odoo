// @ts-check
/** @odoo-module native */

import { download } from "@web/core/network/download";

/** @import { Context, ReportAction } from "../action_service.js" */

/**
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
    if (action.data && Object.keys(action.data).length) {
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
