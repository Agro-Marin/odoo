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
    // FullCalendar v7 (with ``weekNumbersWithinDays: false``) renders the
    // month-grid week number as the first child of each ``.fc-daygrid-row`` --
    // a sibling of the day cells, not nested inside the first one as in v6 --
    // but it does NOT emit a matching header cell, so the header row has one
    // fewer column than the body rows.
    //
    // The body week number is tagged ``.o-fc-week`` via the renderer's
    // ``inlineWeekNumberClass`` option (it survives FullCalendar's body
    // re-renders, which an imperative class here would not). All that remains
    // is to prepend an aligned header cell so the header keeps the same column
    // count as the body. The cell must NOT carry ``.fc-col-header-cell`` --
    // that class backs day-name queries and would pollute them with the week
    // label. The shared ``width: 3ch`` rule on ``.o-fc-week, .o-fc-week-header``
    // (calendar_renderer.scss) aligns it above the equal-width day columns.
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
