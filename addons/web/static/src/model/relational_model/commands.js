// @ts-check

/** @module @web/model/relational_model/commands - x2many ORM command constants and factory functions */

/**
 * One2many and Many2many fields expect a special command to manipulate the
 * relation they implement.
 *
 * Internally, each command is a 3-elements tuple where the first element is a
 * mandatory integer that identifies the command, the second element is either
 * the related record id to apply the command on (commands update, delete,
 * unlink and link) either 0 (commands create, clear and set), the third
 * element is either the ``values`` to write on the record (commands create
 * and update) either the new ``ids`` list of related records (command set),
 * either 0 (commands delete, unlink, link, and clear).
 */
export const x2ManyCommands = {
    // (0, virtualID | false, { values })
    CREATE: 0,
    create(virtualID, values) {
        delete values.id;
        return [x2ManyCommands.CREATE, virtualID || false, values];
    },
    // (1, id, { values })
    UPDATE: 1,
    update(id, values) {
        delete values.id;
        return [x2ManyCommands.UPDATE, id, values];
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
