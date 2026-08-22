// @ts-check
/** @odoo-module native */

import { DateTime, Settings } from "@web/core/l10n/luxon";

const SERVER_DATE_FORMAT = "yyyy-MM-dd";
const SERVER_TIME_FORMAT = "HH:mm:ss";
const SERVER_DATETIME_FORMAT = `${SERVER_DATE_FORMAT} ${SERVER_TIME_FORMAT}`;

/** @type {WeakMap<any, string>} */
const dateCache = new WeakMap();
/** @type {WeakMap<any, string>} */
const dateTimeCache = new WeakMap();

/**
 * @param {any} value
 * @returns {boolean}
 */
function isSerializable(value) {
    return Boolean(value) && value.isValid !== false;
}

/**
 * @param {any} value
 * @returns {string|false}
 */
export function serializeDate(value) {
    if (!isSerializable(value)) {
        return false;
    }
    let serialized = dateCache.get(value);
    if (serialized === undefined) {
        serialized = String(
            value.toFormat(SERVER_DATE_FORMAT, { numberingSystem: "latn" }),
        );
        dateCache.set(value, serialized);
    }
    return serialized;
}

/**
 * @param {any} value
 * @returns {string|false}
 */
export function serializeDateTime(value) {
    if (!isSerializable(value)) {
        return false;
    }
    let serialized = dateTimeCache.get(value);
    if (serialized === undefined) {
        serialized = String(
            value
                .setZone("utc")
                .toFormat(SERVER_DATETIME_FORMAT, { numberingSystem: "latn" }),
        );
        dateTimeCache.set(value, serialized);
    }
    return serialized;
}

/**
 * @param {string} value
 * @returns {any}
 */
export function deserializeDate(value) {
    return DateTime.fromSQL(value, {
        numberingSystem: "latn",
        zone: "default",
    }).reconfigure({
        numberingSystem: Settings.defaultNumberingSystem,
    });
}

/**
 * @param {string} value
 * @param {{tz?: string}} [options]
 * @returns {any}
 */
export function deserializeDateTime(value, options = {}) {
    return DateTime.fromSQL(value, { numberingSystem: "latn", zone: "utc" })
        .setZone(options?.tz || "default")
        .reconfigure({
            numberingSystem: Settings.defaultNumberingSystem,
        });
}
