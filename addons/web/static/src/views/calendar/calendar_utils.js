// @ts-check
/** @odoo-module native */

/** @module @web/views/calendar/calendar_utils - Utility functions for calendar record-to-event conversion, color mapping, and date formatting */

/**
 * Convert a calendar record into a FullCalendar event object.
 *
 * @param {Object} record - calendar record with id, title, start, end, isAllDay
 * @param {boolean} [forceAllDay=false] - treat the event as all-day regardless of record flags
 * @returns {{ id: number, title: string, start: string, end: string, allDay: boolean }}
 */
export function convertRecordToEvent(record, forceAllDay = false) {
    const allDay =
        forceAllDay ||
        record.isAllDay ||
        record.end.diff(record.start, "hours").hours >= 24;
    let end = record.end;
    if (
        record.isAllDay ||
        (allDay && end.toMillis() !== end.startOf("day").toMillis())
    ) {
        end = end.plus({ days: 1 });
    }
    return {
        id: record.id,
        title: record.title,
        start: record.start.toISO(),
        end: end.toISO(),
        allDay,
    };
}

const CSS_COLOR_REGEX =
    /^((#[A-F0-9]{3})|(#[A-F0-9]{6})|((hsl|rgb)a?\(\s*(?:(\s*\d{1,3}%?\s*),?){3}(\s*,[0-9.]{1,4})?\))|)$/i;
// Module-global on purpose: a given key keeps the same color across every
// calendar view visited during the session (renderers, popovers, filter
// panels all resolve colors through this map).
const colorMap = new Map();
/**
 * Map a key to a stable calendar color index or CSS color string.
 *
 * CSS color strings are returned as-is. Numeric keys are mapped to a
 * palette index (1-55). Other keys hash to a deterministic index (1-24)
 * derived from the key itself, so the color is stable across sessions and
 * independent of which view was visited first.
 *
 * @param {string|number|false} key - color key (record id, CSS color, or falsy)
 * @returns {string|number|false} palette index, CSS color string, or false
 */
export function getColor(key) {
    if (!key) {
        return false;
    }
    if (colorMap.has(key)) {
        return colorMap.get(key);
    }

    if (typeof key === "string" && CSS_COLOR_REGEX.test(key)) {
        colorMap.set(key, key);
    } else if (typeof key === "number") {
        colorMap.set(key, ((key - 1) % 55) + 1);
    } else {
        const stringKey = String(key);
        let hash = 0;
        for (let i = 0; i < stringKey.length; i++) {
            hash = (hash * 31 + stringKey.charCodeAt(i)) | 0;
        }
        colorMap.set(key, (Math.abs(hash) % 24) + 1);
    }

    return colorMap.get(key);
}

/**
 * Sort calendar filters by type priority, then by label.
 *
 * Filters are grouped by their `type` following the order given in
 * `typePriority` (a type absent from the list sorts last). Within a group,
 * `dynamic` filters that have no value (e.g. "Open Shifts") are pushed to the
 * end; the remaining filters are ordered case-/accent-insensitively by label
 * with natural numeric ordering.
 *
 * @param {Array<{ type: string, value: any, label: string }>} filters
 * @param {string[]} typePriority - filter types in the desired priority order
 * @returns {Array} a new array of filters, sorted
 */
export function sortCalendarFilters(filters, typePriority) {
    return filters.toSorted((a, b) => {
        if (a.type === b.type) {
            const va = a.value ? -1 : 0;
            const vb = b.value ? -1 : 0;
            // Condition to put unvaluable item (eg: Open Shifts) at the end of the sorted list.
            if (a.type === "dynamic" && va !== vb) {
                return va - vb;
            }
            return a.label.localeCompare(b.label, undefined, {
                numeric: true,
                sensitivity: "base",
                ignorePunctuation: true,
            });
        } else {
            return typePriority.indexOf(a.type) - typePriority.indexOf(b.type);
        }
    });
}

/**
 * Format a start/end date pair as a human-readable date span string.
 *
 * Same-month ranges are collapsed (e.g. "August 4-5, 2019"), same-day
 * ranges show a single date, and cross-month ranges show full dates.
 *
 * @param {any} start
 * @param {any} end
 * @returns {string} formatted date span
 */
export function getFormattedDateSpan(start, end) {
    const isSameDay = start.hasSame(end, "days");

    if (!isSameDay && start.hasSame(end, "month")) {
        // Simplify date-range if an event occurs into the same month (eg. "August 4-5, 2019")
        return `${start.toFormat("LLLL d")}-${end.toFormat("d, y")}`;
    } else {
        return isSameDay
            ? start.toFormat("DDD")
            : `${start.toFormat("DDD")} - ${end.toFormat("DDD")}`;
    }
}
