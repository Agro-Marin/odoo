// @ts-check
/** @odoo-module native */

import { serializeDate, serializeDateTime } from "@web/core/l10n/dates";
/**
 * @param {string} scale
 * @param {any} date
 * @param {number} firstDayOfWeek
 * @param {boolean} monthOverflow
 * @returns {{ start: any, end: any }}
 */
export function computeCalendarRange(scale, date, firstDayOfWeek, monthOverflow) {
    let start = date;
    let end = date;

    if (scale !== "week") {
        start = start.startOf(scale);
        end = end.endOf(scale);
    }

    if (scale === "week" || (scale === "month" && monthOverflow)) {
        const currentWeekOffset = (start.weekday - firstDayOfWeek + 7) % 7;
        start = start.minus({ days: currentWeekOffset });
        end = start.plus({ weeks: scale === "week" ? 1 : 6, days: -1 });
    }

    start = start.startOf("day");
    end = end.endOf("day");

    return { start, end };
}

/**
 * @param {{ date_start: string, date_stop?: string, date_delay?: string }} fieldMapping
 * @param {"date" | "datetime"} dateStartType
 * @param {{ start: any, end: any }} range
 * @returns {any[][]}
 */
export function computeRangeDomain(fieldMapping, dateStartType, range) {
    const serializeFn = dateStartType === "date" ? serializeDate : serializeDateTime;
    const formattedEnd = serializeFn(range.end);
    const formattedStart = serializeFn(range.start);

    const domain = [[fieldMapping.date_start, "<=", formattedEnd]];
    if (fieldMapping.date_stop) {
        domain.push([fieldMapping.date_stop, ">=", formattedStart]);
    } else if (!fieldMapping.date_delay) {
        domain.push([fieldMapping.date_start, ">=", formattedStart]);
    }
    return domain;
}

/**
 * @param {Record<string, { filters: { active: boolean, value: any }[] }>} filterSections
 * @param {Record<string, { writeResModel?: string }>} filtersInfo
 * @returns {any[][]}
 */
export function computeFiltersDomain(filterSections, filtersInfo) {
    const authorizedValues = {};
    const avoidValues = {};

    for (const [fieldName, filterSection] of Object.entries(filterSections)) {
        const filterSectionInfo = filtersInfo[fieldName];
        for (const filter of filterSection.filters) {
            if (filterSectionInfo.writeResModel) {
                if (!authorizedValues[fieldName]) {
                    authorizedValues[fieldName] = [];
                }
                if (filter.active) {
                    authorizedValues[fieldName].push(filter.value);
                }
            } else {
                if (!filter.active) {
                    if (!avoidValues[fieldName]) {
                        avoidValues[fieldName] = [];
                    }
                    avoidValues[fieldName].push(filter.value);
                }
            }
        }
    }

    const domain = [];
    for (const field of Object.keys(authorizedValues)) {
        domain.push([field, "in", authorizedValues[field]]);
    }
    for (const field of Object.keys(avoidValues)) {
        if (avoidValues[field].length > 0) {
            domain.push([field, "not in", avoidValues[field]]);
        }
    }
    return domain;
}
