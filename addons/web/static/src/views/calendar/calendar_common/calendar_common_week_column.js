// @ts-check
/** @odoo-module native */

/**
 * @param {Object} params
 * @param {HTMLElement} params.el
 * @param {string} params.weekText
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
