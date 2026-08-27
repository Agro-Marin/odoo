// @ts-check
/** @odoo-module native */

/**
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
