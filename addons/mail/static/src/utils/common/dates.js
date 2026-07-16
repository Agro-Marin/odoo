/** @odoo-module native */
import { luxon } from "@web/core/l10n/luxon";
const { DateTime } = luxon;

/**
 * @param {luxon.DateTime} datetime
 */
export function computeDelay(datetime) {
    if (!datetime) {
        return 0;
    }
    const today = DateTime.now().startOf("day");
    return datetime.diff(today, "days").days;
}

export function getMsToTomorrow() {
    const now = new Date();
    const night = new Date(
        now.getFullYear(),
        now.getMonth(),
        now.getDate() + 1, // the next day
        0,
        0,
        0, // at 00:00:00 hours
    );
    return night.getTime() - now.getTime();
}

export function isToday(datetime) {
    if (!datetime) {
        return false;
    }
    // hasSame, not locale-string comparison: each side of the string compare
    // rendered in its own zone (wrong for a DateTime carrying a non-local
    // zone) and paid two locale formats per call — this runs per rendered
    // notification item
    return datetime.hasSame(DateTime.now(), "day");
}
