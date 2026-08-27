// @ts-check
/** @odoo-module native */

/**
 * The wire shape of one x2many command: an opcode, the row it targets, and a
 * payload whose meaning depends on the opcode. `false` is a real target -- CLEAR
 * and SET address the whole list, and CREATE addresses a row that has no id yet.
 *
 * Declared here because this is where the vocabulary is. It used to be spelled
 * four different ways by the two modules that build and reconcile these
 * commands -- `[number, string|number, any?]`, `[number, any, any?]`,
 * `number[]`, and a local `X2ManyCommand` -- which is how a ledger entry came
 * to be typed `{ command: number[] }` while every command in it had a string or
 * an object in it.
 *
 * The target slot is `any` on purpose. What may sit there is decided by the
 * opcode -- a row id for LINK/UNLINK/UPDATE/DELETE, a virtual id for CREATE,
 * `false` for CLEAR and SET -- and expressing that is a discriminated union on
 * the opcode that nobody has written. Declaring the slot `number | string |
 * false` instead was measured: it is more truthful and costs 21 tsc errors in
 * `static_list_command_engine.js` alone, every one of them a site the opcode
 * has already narrowed and the checker cannot see. Narrow at the ledger
 * boundary, where a row id really is a row id.
 *
 * @typedef {number | string} X2ManyRowId
 * @typedef {[number, any, any?]} X2ManyCommand
 */

export const x2ManyCommands = {
    CREATE: 0,
    /** @returns {X2ManyCommand} */
    create(virtualID, values) {
        const vals = { ...values };
        delete vals.id;
        return [x2ManyCommands.CREATE, virtualID || false, vals];
    },
    UPDATE: 1,
    /** @returns {X2ManyCommand} */
    update(id, values) {
        const vals = { ...values };
        delete vals.id;
        return [x2ManyCommands.UPDATE, id, vals];
    },
    DELETE: 2,
    /** @returns {X2ManyCommand} */
    delete(id) {
        return [x2ManyCommands.DELETE, id, false];
    },
    UNLINK: 3,
    /** @returns {X2ManyCommand} */
    unlink(id) {
        return [x2ManyCommands.UNLINK, id, false];
    },
    LINK: 4,
    /** @returns {X2ManyCommand} */
    link(id) {
        return [x2ManyCommands.LINK, id, false];
    },
    CLEAR: 5,
    /** @returns {X2ManyCommand} */
    clear() {
        return [x2ManyCommands.CLEAR, false, false];
    },
    SET: 6,
    /** @returns {X2ManyCommand} */
    set(ids) {
        return [x2ManyCommands.SET, false, ids];
    },
};
