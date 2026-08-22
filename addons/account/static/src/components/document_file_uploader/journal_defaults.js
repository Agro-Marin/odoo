/** @odoo-module native */

const MOVE_TYPE_BY_JOURNAL_TYPE = {
    sale: "out_invoice",
    purchase: "in_invoice",
};

/**
 * The move type a document uploaded into a journal defaults to.
 *
 * @param {string} journalType value of `account.journal.type`
 * @returns {string} a value of `account.move.move_type`
 */
export function defaultMoveTypeForJournal(journalType) {
    return MOVE_TYPE_BY_JOURNAL_TYPE[journalType] ?? "entry";
}
