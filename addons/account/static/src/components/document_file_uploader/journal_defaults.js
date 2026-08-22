/** @odoo-module native */

const MOVE_TYPE_BY_JOURNAL_TYPE = {
    sale: "out_invoice",
    purchase: "in_invoice",
};

/**
 * @param {string} journalType
 * @returns {string}
 */
export function defaultMoveTypeForJournal(journalType) {
    return MOVE_TYPE_BY_JOURNAL_TYPE[journalType] ?? "entry";
}
