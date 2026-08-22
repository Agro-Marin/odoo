/** @odoo-module native */

/**
 * @returns {string}
 */
export function generateId() {
    return Math.floor(Math.random() * Math.pow(2, 52)).toString();
}

/**
 * @param {string} idA
 * @param {string} idB
 * @returns {number}
 */
export function compareIds(idA, idB) {
    const a = String(idA);
    const b = String(idB);
    return a < b ? -1 : a > b ? 1 : 0;
}
