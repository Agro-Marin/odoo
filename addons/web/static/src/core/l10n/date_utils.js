// @ts-check
/** @odoo-module native */

import { localization } from "@web/core/l10n/localization";
import { DateTime } from "@web/core/l10n/luxon";
import { ensureArray } from "@web/core/utils/collections/arrays";

/**
 * @param {any} d1
 * @param {any} d2
 * @returns {boolean}
 */
export function areDatesEqual(d1, d2) {
    if (Array.isArray(d1) || Array.isArray(d2)) {
        d1 = ensureArray(d1);
        d2 = ensureArray(d2);
        return (
            d1.length === d2.length &&
            d1.every((/** @type {any} */ d1Val, /** @type {number} */ i) =>
                areDatesEqual(d1Val, d2[i]),
            )
        );
    }
    if (!d1 && !d2) {
        return true;
    }
    if (d1 instanceof DateTime && d2 instanceof DateTime && d1 !== d2) {
        return d1.equals(d2);
    } else {
        return d1 === d2;
    }
}

/**
 * @param {any} desired
 * @param {any} minDate
 * @param {any} maxDate
 * @returns {any}
 */
export function clampDate(desired, minDate, maxDate) {
    if (maxDate < desired) {
        return maxDate;
    }
    if (minDate > desired) {
        return minDate;
    }
    return desired;
}

/**
 * @param {any} date
 * @returns {{ year: number, week: number, startDate: any }}
 */
export function getLocalYearAndWeek(date) {
    if (!date.isLuxonDateTime) {
        date = DateTime.fromJSDate(date);
    }
    const { weekStart } = localization;
    const startDate = date.minus({ days: (date.weekday + 7 - weekStart) % 7 });
    date =
        weekStart > 1 && weekStart < 5
            ? startDate.minus({ days: (startDate.weekday + 6) % 7 })
            : startDate.plus({ days: (8 - startDate.weekday) % 7 });
    date = date.plus({ days: 6 });
    const jan4 = DateTime.local(date.year, 1, 4);
    let diffDays, year;
    if (date < jan4) {
        diffDays = date.diff(jan4.minus({ years: 1 }), "day").days;
        year = date.year - 1;
    } else {
        diffDays = date.diff(jan4, "day").days;
        year = date.year;
    }
    return {
        year,
        week: Math.trunc(diffDays / 7) + 1,
        startDate,
    };
}

/**
 * @param {any} date
 * @returns {any}
 */
export function getStartOfLocalWeek(date) {
    const { weekStart } = localization;
    const weekday = date.weekday < weekStart ? weekStart - 7 : weekStart;
    return date.set({ weekday }).startOf("day");
}

/**
 * @param {any} date
 * @returns {any}
 */
export function getEndOfLocalWeek(date) {
    return getStartOfLocalWeek(date).plus({ days: 6 }).endOf("day");
}

/**
 * @param {any} value
 * @param {[any, any]} range
 * @returns {boolean}
 */
export function isInRange(value, range) {
    if (!value || !range) {
        return false;
    }
    if (Array.isArray(value)) {
        const actualValues = value.filter(Boolean).sort((x, y) => x - y);
        if (actualValues.length < 2) {
            return isInRange(actualValues[0], range);
        }
        return (
            (actualValues[0] <= range[0] && range[0] <= actualValues[1]) ||
            (range[0] <= actualValues[0] && actualValues[0] <= range[1])
        );
    } else {
        return range[0] <= value && value <= range[1];
    }
}

/**
 * @returns {any}
 */
export function today() {
    return DateTime.local().startOf("day");
}
