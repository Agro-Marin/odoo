// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/command_builder */

import { x2ManyCommands } from "@web/core/network/commands";

const { CREATE, UPDATE, UNLINK, LINK, SET } = x2ManyCommands;

/**
 * @param {Array<[number, string|number, any?]>} commands
 * @param {Object} params
 * @param {Object} params.unknownRecordCommands
 * @param {Object} params.fields
 * @param {Object} params.activeFields
 * @param {Object} params.context
 * @param {boolean} [params.withReadonly]
 * @param {(id: string|number) => Object|undefined} params.getRecord
 * @param {(record: Object, withReadonly: boolean) => Object} params.getRecordChanges
 * @param {(values: Object, fields: Object, activeFields: Object, options: Object) => Object} params.convertUnityValues
 * @returns {Array<[number, string|number, any?]>}
 */
export function serializeCommands(commands, params) {
    const {
        unknownRecordCommands,
        fields,
        activeFields,
        context,
        withReadonly = false,
        getRecord,
        getRecordChanges,
        convertUnityValues,
    } = params;

    const result = [];

    for (const command of commands) {
        if (command[0] === UPDATE && command[1] in unknownRecordCommands) {
            const uCommands = unknownRecordCommands[command[1]];
            const deferredValues = {};
            for (const uCommand of uCommands) {
                Object.assign(deferredValues, uCommand[2]);
            }
            const values = convertUnityValues(deferredValues, fields, activeFields, {
                withReadonly,
                context,
            });
            const record = getRecord(command[1]);
            if (record) {
                Object.assign(values, getRecordChanges(record, withReadonly));
            }
            result.push([UPDATE, command[1], values]);
        } else if (command[0] === CREATE || command[0] === UPDATE) {
            const record = getRecord(command[1]);
            if (!record) {
                continue;
            }
            if (command[0] === CREATE && record?.resId) {
                result.push([LINK, record.resId, false]);
            } else {
                const values = getRecordChanges(record, withReadonly);
                if (command[0] === CREATE || Object.keys(values).length) {
                    result.push([command[0], command[1], values]);
                }
            }
        } else {
            result.push(command);
        }
    }

    return /** @type {[number, string | number, any?][]} */ (result);
}

/**
 * @param {Array<{command: number[], index: number}>} ownCommands
 * @returns {boolean}
 */
export function shouldEmitDelete(ownCommands) {
    const hasCreate = ownCommands.some((x) => x.command[0] === CREATE);
    ownCommands.splice(0);
    return !hasCreate;
}

/**
 * @param {Array<{command: number[], index: number}>} ownCommands
 * @returns {boolean}
 */
export function shouldEmitUnlink(ownCommands) {
    if (ownCommands.some((x) => x.command[0] === CREATE)) {
        ownCommands.splice(0);
        return false;
    }
    const linkIndex = ownCommands.findIndex((x) => x.command[0] === LINK);
    if (linkIndex >= 0) {
        ownCommands.splice(linkIndex, 1);
        if (!ownCommands.some((x) => x.command[0] === LINK)) {
            // The LINK is gone, so the staged UPDATEs are moot -- but an UNLINK
            // BEFORE it means the row was a server member the user had already
            // removed, and dropping that too silently re-links it on save.
            const unlinks = ownCommands.filter((x) => x.command[0] === UNLINK);
            ownCommands.splice(0, ownCommands.length, ...unlinks);
        }
        return false;
    }
    return true;
}

/**
 * Drop *recordId* from a leading SET command, so unlinking a row the same batch
 * just SET is expressed by shortening the SET rather than by appending an
 * UNLINK the server would apply to a row that was never linked.
 *
 * Only the SET payload is touched. The caller owns the rest: on a true return
 * it clears that id's own commands, and it rebuilds `list._commands` from its
 * own index afterwards -- so splicing *allCommands* here would be writing to an
 * array that is about to be replaced.
 *
 * @param {Array<[number, any, any?]>} allCommands
 * @param {string|number} recordId
 * @returns {boolean}
 */
export function absorbUnlinkIntoSet(allCommands, recordId) {
    const firstCommand = allCommands[0];
    if (!firstCommand || firstCommand[0] !== SET) {
        return false;
    }
    const ids = firstCommand[2];
    if (!ids.includes(recordId)) {
        return false;
    }
    firstCommand[2] = ids.filter((id) => id !== recordId);
    return true;
}

/**
 * @param {Array<{command: number[], index: number}>} ownCommands
 * @returns {boolean}
 */
export function isUpdateRedundant(ownCommands) {
    return ownCommands.some((x) => x.command[0] === CREATE || x.command[0] === UPDATE);
}
