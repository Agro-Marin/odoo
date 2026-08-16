/** @odoo-module native */
import { luxon } from "@web/core/l10n/luxon";
const { DateTime } = luxon;

/**
 * @param {luxon.DateTime} datetime
 * @returns {number}
 */
export function computeDelay(datetime) {
    if (!datetime) {
        return 0;
    }
    const today = DateTime.now().startOf("day");
    return datetime.diff(today, "days").days;
}

/** @returns {number} */
export function getMsToTomorrow() {
    const now = DateTime.now();
    return now.plus({ days: 1 }).startOf("day").diff(now).milliseconds;
}

/**
 * @param {luxon.DateTime} datetime
 * @returns {boolean}
 */
export function isToday(datetime) {
    if (!datetime) {
        return false;
    }
    return datetime.hasSame(DateTime.now(), "day");
}
