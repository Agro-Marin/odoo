/** @odoo-module native */

import {
    deserializeDate,
    deserializeDateTime,
    serializeDate,
    serializeDateTime,
} from "@web/core/l10n/dates";
import { _t } from "@web/core/translation";
import { inRangeProviderRegistry } from "@web/core/tree";

/**
 * The ranges the domain editor may offer, filled by `date_range_service`
 * before the editor renders and read synchronously from here afterwards.
 *
 * A module-level cache rather than a service lookup because the registry's
 * contract is synchronous: `getOptions` is called while the value editor is
 * being built, with no `env` in hand and no room to await anything.
 *
 * @type {Array<Object>}
 */
let ranges = [];

/**
 * @param {Array<Object>} loadedRanges - date.range records
 */
export function setDateRanges(loadedRanges) {
    ranges = loadedRanges || [];
}

/**
 * A range covers whole days, so on a datetime field it runs from the first
 * instant of its start day to the last of its end day. Getting these the wrong
 * way round silently narrows the filter by almost two days.
 *
 * @param {string} date - YYYY-MM-DD
 * @param {string} fieldType - 'date' or 'datetime'
 * @param {boolean} endOfDay
 * @returns {string}
 */
function bound(date, fieldType, endOfDay) {
    if (fieldType === "date") {
        return date;
    }
    const day = deserializeDate(date);
    return serializeDateTime(endOfDay ? day.endOf("day") : day.startOf("day"));
}

/**
 * @param {string} value - a stored bound
 * @param {string} fieldType
 * @returns {string} the plain date it falls on
 */
function toDate(value, fieldType) {
    if (fieldType === "date") {
        return value;
    }
    // Through the timezone, not by slicing the first ten characters: a bound is
    // stored in UTC, and the last instant of a day is the *next* UTC date for
    // any user east of Greenwich. `deserializeDateTime` brings it back to the
    // user's timezone first, which is where the day boundary was drawn.
    return serializeDate(deserializeDateTime(value));
}

/**
 * @param {number} id
 * @returns {string}
 */
function optionId(id) {
    return `date_range:${id}`;
}

inRangeProviderRegistry.add("date_range", {
    label: _t("Periods"),

    getOptions(fieldType) {
        if (!["date", "datetime"].includes(fieldType)) {
            return [];
        }
        return ranges.map((range) => ({
            id: optionId(range.id),
            label: range.name,
            // type_id is a [id, display_name] pair; the display name is what
            // the user configured the type as, so it is the group heading.
            group: range.type_id ? range.type_id[1] : undefined,
        }));
    },

    resolve(id, fieldType) {
        if (!["date", "datetime"].includes(fieldType)) {
            return null;
        }
        const range = ranges.find((r) => optionId(r.id) === id);
        if (!range) {
            return null;
        }
        return [
            bound(range.date_start, fieldType, false),
            bound(range.date_end, fieldType, true),
        ];
    },

    match(fieldType, start, end) {
        if (!["date", "datetime"].includes(fieldType) || !start || !end) {
            return null;
        }
        if (typeof start !== "string" || typeof end !== "string") {
            return null;
        }
        const startDate = toDate(start, fieldType);
        const endDate = toDate(end, fieldType);
        const range = ranges.find(
            (r) => r.date_start === startDate && r.date_end === endDate,
        );
        return range ? optionId(range.id) : null;
    },
});
