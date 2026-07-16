// @ts-check
/** @odoo-module native */

/** @module @web/core/l10n/date_serialization - Server-format date serialization and deserialization with WeakMap caching */

import { DateTime, Settings } from "@web/core/l10n/luxon";

const SERVER_DATE_FORMAT = "yyyy-MM-dd";
const SERVER_TIME_FORMAT = "HH:mm:ss";
const SERVER_DATETIME_FORMAT = `${SERVER_DATE_FORMAT} ${SERVER_TIME_FORMAT}`;

/** @type {WeakMap<any, string>} */
const dateCache = new WeakMap();
/** @type {WeakMap<any, string>} */
const dateTimeCache = new WeakMap();

/**
 * Formats the given DateTime to the server date format ("yyyy-MM-dd").
 * Results are cached per DateTime instance.
 *
 * @param {any} value - Luxon DateTime
 * @returns {string|false} the serialized date, or `false` for falsy input
 */
export function serializeDate(value) {
    // Guard falsy input like the sibling deserialize/format helpers: a WeakMap
    // key must be an object, so ``dateCache.set(false, …)`` would throw
    // "Invalid value used as weak map key".
    if (!value) {
        return false;
    }
    if (!dateCache.has(value)) {
        dateCache.set(
            value,
            value.toFormat(SERVER_DATE_FORMAT, { numberingSystem: "latn" }),
        );
    }
    return dateCache.get(value);
}

/**
 * Formats the given DateTime to the server datetime format ("yyyy-MM-dd HH:mm:ss").
 * The value is converted to UTC before formatting. Results are cached.
 *
 * @param {any} value - Luxon DateTime
 * @returns {string|false} the serialized datetime, or `false` for falsy input
 */
export function serializeDateTime(value) {
    // See serializeDate: falsy input can't be a WeakMap key.
    if (!value) {
        return false;
    }
    if (!dateTimeCache.has(value)) {
        dateTimeCache.set(
            value,
            value
                .setZone("utc")
                .toFormat(SERVER_DATETIME_FORMAT, { numberingSystem: "latn" }),
        );
    }
    return dateTimeCache.get(value);
}

/**
 * Parses a serialized date string (e.g. "2018-01-01") into a Luxon DateTime
 * in the user's timezone.
 *
 * @param {string} value
 * @returns {any} Luxon DateTime
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
 * Parses a serialized datetime string (e.g. "2018-01-01 00:00:00") expressed
 * in UTC into a Luxon DateTime in the user's timezone.
 *
 * @param {string} value
 * @param {{tz?: string}} [options]
 * @returns {any} Luxon DateTime
 */
export function deserializeDateTime(value, options = {}) {
    return DateTime.fromSQL(value, { numberingSystem: "latn", zone: "utc" })
        .setZone(options?.tz || "default")
        .reconfigure({
            numberingSystem: Settings.defaultNumberingSystem,
        });
}
