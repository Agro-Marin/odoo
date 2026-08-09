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

/**
 * Milliseconds until the next midnight **in the user's timezone**.
 *
 * Must use luxon, not `new Date()`: `@web/boot/start` sets
 * `Settings.defaultZone` from the Odoo user's timezone, which is not
 * necessarily the browser's. `computeDelay` and `isToday` both resolve "today"
 * through luxon, so building this delay from the browser's calendar armed the
 * caller's re-render (Activity's midnight timer) at the wrong instant -- by the
 * offset between the two zones -- leaving the "delay" label stale, or firing it
 * early while the label still had to change later.
 *
 * The zone is the *only* thing that was wrong: the previous
 * `new Date(y, m, d + 1, 0, 0, 0)` did land on a true local midnight, DST
 * transitions included -- it just picked the browser's midnight. Keep using
 * `plus({ days: 1 }).startOf("day")` rather than adding 24h of milliseconds,
 * which is the formulation that would actually drift on a transition day.
 */
export function getMsToTomorrow() {
    const now = DateTime.now();
    return now.plus({ days: 1 }).startOf("day").diff(now).milliseconds;
}

export function isToday(datetime) {
    if (!datetime) {
        return false;
    }
    // hasSame, not locale-string comparison: comparing rendered strings uses
    // each side's own zone (wrong for a non-local zone) and costs two locale
    // formats per call, on a path that runs per rendered notification item
    return datetime.hasSame(DateTime.now(), "day");
}
