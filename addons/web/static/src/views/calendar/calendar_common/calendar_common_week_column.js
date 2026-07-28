// @ts-check
/** @odoo-module native */

/** @module @web/views/calendar/calendar_common/calendar_common_week_column - Inserts week-number columns into FullCalendar grid headers and body rows */

/**
 * Complete FullCalendar v7's month-grid week column.
 *
 * Tags each body week-number element as ``.o-fc-week`` and prepends a matching
 * ``.o-fc-week-header`` to the header row so the header and body grids keep the
 * same column count.
 *
 * @param {Object} params
 * @param {HTMLElement} params.el - FullCalendar root element
 * @param {string} params.weekText - header label for the week column
 */
export function makeWeekColumn({ el, weekText }) {
    const headerCell = el.querySelector(".fc-col-header-cell");
    const headerRow = headerCell?.parentElement;
    if (headerRow && !headerRow.querySelector(".o-fc-week-header")) {
        const weekHeader = document.createElement(headerCell.tagName);
        weekHeader.classList.add("o-fc-week-header");
        weekHeader.setAttribute("role", "columnheader");
        weekHeader.innerText = weekText;
        headerRow.prepend(weekHeader);
    }
}
