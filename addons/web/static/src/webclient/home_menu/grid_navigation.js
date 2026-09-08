// @ts-check
/** @odoo-module native */

/**
 * The arrow keys' view of the launcher: where each focusable item sits, and
 * where an arrow moves from there. Pure arithmetic over the shape on screen —
 * no DOM, no component — so the geometry can be read and tested on its own.
 *
 * Items carry one flat index across the whole surface, tiles first and the
 * matching menus after them, which is the index `focusedIndex` holds.
 */

/**
 * The rows on screen: each tile section wraps at the grid's width, and each
 * matching menu is a row of its own beneath them.
 *
 * @param {number[]} sectionSizes how many tiles in each section, in order
 * @param {number} perRow the grid's width in tiles
 * @param {number} [singleRows] items below the grid, one row each
 * @returns {number[][]} flat indices, row by row
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
 * Where an arrow key lands. Both axes wrap, and a move onto a shorter row
 * lands on its last item rather than falling off it.
 *
 * @param {number[][]} rows as `gridRows` returns them
 * @param {number | null} from the flat index the focus is on, or none yet
 * @param {GridMove | string} move
 * @returns {number | null} the flat index to focus, or null to leave it alone
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
