// @ts-check
/** @odoo-module native */

/**
 * @param {Object} record
 * @param {boolean} [forceAllDay=false]
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
const colorMap = new Map();
/**
 * @param {string|number|false} key
 * @returns {string|number|false}
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
 * @param {Array<{ type: string, value: any, label: string }>} filters
 * @param {string[]} typePriority
 * @returns {Array}
 */
export function sortCalendarFilters(filters, typePriority) {
    return filters.toSorted((a, b) => {
        if (a.type === b.type) {
            const va = a.value ? -1 : 0;
            const vb = b.value ? -1 : 0;
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
 * @param {any} start
 * @param {any} end
 * @returns {string}
 */
export function getFormattedDateSpan(start, end) {
    const isSameDay = start.hasSame(end, "days");

    if (!isSameDay && start.hasSame(end, "month")) {
        return `${start.toFormat("LLLL d")}-${end.toFormat("d, y")}`;
    } else {
        return isSameDay
            ? start.toFormat("DDD")
            : `${start.toFormat("DDD")} - ${end.toFormat("DDD")}`;
    }
}

/**
 * @param {any} record
 * @returns {string[]}
 */
export function baseEventClassNames(record) {
    const classes = ["o_event"];
    if (!record) {
        return classes;
    }
    const color = getColor(record.colorIndex);
    if (typeof color === "number") {
        classes.push(`o_calendar_color_${color}`);
    } else if (typeof color !== "string") {
        classes.push("o_calendar_color_0");
    }
    if (record.isHatched) {
        classes.push("o_event_hatched");
    }
    if (record.isStriked) {
        classes.push("o_event_striked");
    }
    return classes;
}

/**
 * @param {HTMLElement} el
 * @param {{ id: string }} event
 * @param {any} record
 * @param {string[]} classes
 * @returns {void}
 */
export function paintMountedEvent(el, event, record, classes) {
    if (classes.length) {
        el.classList.add(...classes);
    }
    el.dataset.eventId = event.id;
    if (!record) {
        return;
    }
    const color = getColor(record.colorIndex);
    if (typeof color === "string") {
        el.style.backgroundColor = color;
    }
}
