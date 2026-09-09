// @ts-check
/** @odoo-module native */

/**
 * @param {number[]} sectionSizes
 * @param {number} perRow
 * @param {number} [singleRows]
 * @returns {number[][]}
 */
export function gridRows(sectionSizes, perRow, singleRows = 0) {
    /** @type {number[][]} */
    const rows = [];
    let index = 0;
    for (const size of sectionSizes) {
        for (let start = 0; start < size; start += perRow) {
            const row = [];
            for (let i = start; i < Math.min(start + perRow, size); i++) {
                row.push(index++);
            }
            rows.push(row);
        }
    }
    for (let i = 0; i < singleRows; i++) {
        rows.push([index++]);
    }
    return rows;
}

/** @typedef {"previousColumn"|"nextColumn"|"previousLine"|"nextLine"} GridMove */

/**
 * @param {number[][]} rows
 * @param {number | null} from
 * @param {GridMove | string} move
 * @returns {number | null}
 */
export function nextFocusedIndex(rows, from, move) {
    if (!rows.length) {
        return null;
    }
    if (from === null) {
        return 0;
    }
    let r = rows.findIndex((row) => row.includes(from));
    if (r === -1) {
        return 0;
    }
    let c = rows[r].indexOf(from);
    switch (move) {
        case "previousColumn":
            c = c > 0 ? c - 1 : rows[r].length - 1;
            break;
        case "nextColumn":
            c = c < rows[r].length - 1 ? c + 1 : 0;
            break;
        case "previousLine":
            r = r > 0 ? r - 1 : rows.length - 1;
            break;
        case "nextLine":
            r = r < rows.length - 1 ? r + 1 : 0;
            break;
        default:
            return null;
    }
    return rows[r][Math.min(c, rows[r].length - 1)];
}
