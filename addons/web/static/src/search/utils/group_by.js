// @ts-check
/** @odoo-module native */

import { BACKEND_INTERVAL_OPTIONS, DEFAULT_INTERVAL } from "./dates.js";

/**
 * @param {string} descr
 */
function errorMsg(descr) {
    return `Invalid groupBy description: ${descr}`;
}

/**
 * @param {string} descr
 * @param {Record<string, any>} [fields]
 * @returns {Record<string, any>}
 */
export function getGroupBy(descr, fields) {
    const [fieldName, rawInterval] = descr.split(":");
    if (!fieldName) {
        throw Error(errorMsg(descr));
    }

    /** @type {string | null | undefined} */
    let interval = rawInterval;
    if (fields) {
        if (!fields[fieldName] && !fieldName.includes(".")) {
            throw Error(errorMsg(descr));
        }
        const isDateField = ["date", "datetime"].includes(fields[fieldName]?.type);
        if (isDateField) {
            interval ||= DEFAULT_INTERVAL;
        } else if (interval) {
            throw Error(errorMsg(descr));
        }
    }
    if (interval && !(interval in BACKEND_INTERVAL_OPTIONS)) {
        throw Error(errorMsg(descr));
    }

    const spec = interval ? `${fieldName}:${interval}` : fieldName;
    return {
        fieldName,
        interval: interval || null,
        spec,
        toJSON() {
            return spec;
        },
    };
}
