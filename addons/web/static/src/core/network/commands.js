// @ts-check
/** @odoo-module native */

export const x2ManyCommands = {
    CREATE: 0,
    create(virtualID, values) {
        const vals = { ...values };
        delete vals.id;
        return [x2ManyCommands.CREATE, virtualID || false, vals];
    },
    UPDATE: 1,
    update(id, values) {
        const vals = { ...values };
        delete vals.id;
        return [x2ManyCommands.UPDATE, id, vals];
    },
    DELETE: 2,
    delete(id) {
        return [x2ManyCommands.DELETE, id, false];
    },
    UNLINK: 3,
    unlink(id) {
        return [x2ManyCommands.UNLINK, id, false];
    },
    LINK: 4,
    link(id) {
        return [x2ManyCommands.LINK, id, false];
    },
    CLEAR: 5,
    clear() {
        return [x2ManyCommands.CLEAR, false, false];
    },
    SET: 6,
    set(ids) {
        return [x2ManyCommands.SET, false, ids];
    },
};
