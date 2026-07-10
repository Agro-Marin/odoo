// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/commands - x2many ORM command constants and factory functions */

/**
 * One2many/Many2many fields use a 3-element command tuple to describe a
 * mutation on the relation: [command, id_or_0, values_or_ids_or_0].
 * - id_or_0: record id for update/delete/unlink/link, else 0 (create/clear/set)
 * - values_or_ids_or_0: values to write (create/update), new ids list (set),
 *   else 0 (delete/unlink/link/clear)
 */
export const x2ManyCommands = {
    // (0, virtualID | false, { values })
    CREATE: 0,
    create(virtualID, values) {
        const { id: _, ...vals } = values;
        return [x2ManyCommands.CREATE, virtualID || false, vals];
    },
    // (1, id, { values })
    UPDATE: 1,
    update(id, values) {
        const { id: _, ...vals } = values;
        return [x2ManyCommands.UPDATE, id, vals];
    },
    // (2, id[, _])
    DELETE: 2,
    delete(id) {
        return [x2ManyCommands.DELETE, id, false];
    },
    // (3, id[, _]) removes relation, but not linked record itself
    UNLINK: 3,
    unlink(id) {
        return [x2ManyCommands.UNLINK, id, false];
    },
    // (4, id[, _])
    LINK: 4,
    link(id) {
        return [x2ManyCommands.LINK, id, false];
    },
    // (5[, _[, _]])
    CLEAR: 5,
    clear() {
        return [x2ManyCommands.CLEAR, false, false];
    },
    // (6, _, ids) replaces all linked records with provided ids
    SET: 6,
    set(ids) {
        return [x2ManyCommands.SET, false, ids];
    },
};
