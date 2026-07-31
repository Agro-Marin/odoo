// @ts-check
/** @odoo-module native */

/** @module @web/search/utils/group_by */

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
 * @returns {Object}
 */
export function getGroupBy(descr, fields) {
    let spec;
    const [fieldName, rawInterval] = descr.split(":");
    /** @type {string | null | undefined} */
    let interval = rawInterval;
    if (!fieldName) {
        throw Error(errorMsg(descr));
    }
    if (fields) {
        if (!fields[fieldName] && !fieldName.includes(".")) {
            throw Error(errorMsg(descr));
        }
        const fieldType = fields[fieldName]?.type;
        if (["date", "datetime"].includes(fieldType)) {
            if (!interval) {
                interval = DEFAULT_INTERVAL;
            } else if (!(interval in BACKEND_INTERVAL_OPTIONS)) {
                throw Error(errorMsg(descr));
            }
            spec = `${fieldName}:${interval}`;
        } else if (interval) {
            throw Error(errorMsg(descr));
        } else {
            spec = fieldName;
            interval = null;
        }
    } else {
        if (interval) {
            if (!(interval in BACKEND_INTERVAL_OPTIONS)) {
                throw Error(errorMsg(descr));
            }
            spec = `${fieldName}:${interval}`;
        } else {
            spec = fieldName;
            interval = null;
        }
    }
    return {
        fieldName,
        interval,
        spec,
        toJSON() {
            return spec;
        },
    };
}
