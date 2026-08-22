/** @odoo-module native */
import { closestElement } from "./dom_traversal.js";

/**
 * @private
 * @param {HTMLTableRowElement|HTMLTableCellElement} trOrTd
 * @returns {number}
 */
export function getRowIndex(trOrTd) {
    const tr = closestElement(trOrTd, "tr");
    return tr.rowIndex;
}

/**
 * @private
 * @param {HTMLTableCellElement} td
 * @returns {number}
 */
export function getColumnIndex(td) {
    return td.cellIndex;
}

/**
 * @param {HTMLTableElement} table
 * @returns {Array<HTMLTableCellElement>}
 */
export function getTableCells(table) {
    return [...table.querySelectorAll("td, th")].filter(
        (cell) => closestElement(cell, "table") === table,
    );
}
