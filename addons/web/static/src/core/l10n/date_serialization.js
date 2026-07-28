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
    if (!value) {
        return false;
    }
    // One map lookup on a hit instead of the has()/set()/get() trio, and the
    // result is a plain string rather than the `string | undefined` a bare
    // `get()` returns however unreachable the miss is.
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
 * Formats the given DateTime to the server datetime format ("yyyy-MM-dd HH:mm:ss").
 * The value is converted to UTC before formatting. Results are cached.
 *
 * @param {any} value - Luxon DateTime
 * @returns {string|false} the serialized datetime, or `false` for falsy input
 */
export function serializeDateTime(value) {
    if (!value) {
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
