/** @odoo-module native */
import { localization } from "@web/core/l10n/localization";
import { luxon } from "@web/core/l10n/luxon";
import { _t } from "@web/core/translation";
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
/**
 * Current time where `partnerTz` is, or null when there is nothing to say
 * because both sides are in the same timezone.
 *
 * @param {string} partnerTz
 * @param {string} currentUserTz
 * @returns {string|null}
 */
export function formatLocalDateTime(partnerTz, currentUserTz) {
    if (!partnerTz || !currentUserTz || partnerTz === currentUserTz) {
        return null;
    }
    const now = DateTime.now();
    const partnerDateTime = now.setZone(partnerTz);
    const currentUserDateTime = now.setZone(currentUserTz);
    const format = currentUserDateTime.hasSame(partnerDateTime, "day")
        ? localization.timeFormat.replace(":ss", "")
        : localization.dateTimeFormat.replace(":ss", "");
    return _t("%(datetime)s local time", {
        datetime: partnerDateTime.toFormat(format),
    });
}

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
