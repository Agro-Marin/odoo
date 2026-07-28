// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/command_builder - x2many ORM command serialization and deduplication (CREATE, UPDATE, LINK, SET, DELETE, UNLINK) */

import { x2ManyCommands } from "./commands.js";

/**
 * Command building and deduplication logic for x2many fields.
 *
 * Extracted from StaticList._getCommands and the deduplication branches
 * of StaticList._applyCommands. No OWL dependency, so testable with plain
 * assert.
 *
 * NOT side-effect free, despite reading that way. {@link serializeCommands} is
 * the only pure function here. The three predicates —
 * {@link shouldEmitDelete}, {@link shouldEmitUnlink} and
 * {@link absorbUnlinkIntoSet} — answer a question AND rewrite the command log
 * they were handed; that pruning is the point, not a side effect, since the
 * caller's next act is to append the command they just authorised. A reader who
 * takes the boolean and skips the mutation gets a save payload that still
 * carries the commands these were supposed to cancel.
 *
 * @see static_list.js for the imperative wrapper that calls these
 */

const { CREATE, UPDATE, LINK, SET } = x2ManyCommands;

/**
 * Serialize pending x2many commands into server-ready ORM command tuples.
 *
 * This is the pure core of StaticList._getCommands. Given a list of pending
 * commands and lookup functions for records and unknown commands, produces
 * the final command list to send to the server.
 *
 * @param {Array<[number, string|number, any?]>} commands - pending command list
 * @param {Object} params
 * @param {Object} params.unknownRecordCommands - deferred commands for unloaded records
 * @param {Object} params.fields - field definitions
 * @param {Object} params.activeFields - active field metadata
 * @param {Object} params.context - ORM context
 * @param {boolean} [params.withReadonly] - include readonly fields in values
 * @param {(id: string|number) => Object|undefined} params.getRecord
 *     Lookup a Record datapoint by id from the cache.
 * @param {(record: Object, withReadonly: boolean) => Object} params.getRecordChanges
 *     Get the server-ready changeset from a Record (calls record._getChanges).
 * @param {(values: Object, fields: Object, activeFields: Object, options: Object) => Object} params.convertUnityValues
 *     Convert unity-format values to server format (fromUnityToServerValues).
 * @returns {Array<[number, string|number, any?]>} server-ready command tuples
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
 * Determine whether a DELETE command should be emitted for a record,
 * given the existing commands for that record.
 *
 * If the record was CREATEd in this session, DELETE cancels the CREATE
 * (net effect: nothing happened). Otherwise, a DELETE command is emitted.
 *
 * MUTATES ``ownCommands``: empties it either way. The record is going away
 * entirely, so anything staged against it is moot — which is precisely what
 * makes DELETE differ from UNLINK below.
 *
 * @param {Array<{command: number[], index: number}>} ownCommands
 *     Existing commands for this record id. Emptied in place.
 * @returns {boolean} true if a DELETE command should be emitted
 */
export function shouldEmitDelete(ownCommands) {
    const hasCreate = ownCommands.some((x) => x.command[0] === CREATE);
    ownCommands.splice(0);
    return !hasCreate;
}

/**
 * Determine whether an UNLINK command should be emitted for a record,
 * given the existing commands for that record.
 *
 * If the record was LINKed in this session, UNLINK cancels the LINK
 * (net effect: nothing happened). Otherwise, an UNLINK command is emitted.
 *
 * MUTATES ``ownCommands``: drops the cancelled LINK, and empties the log once
 * no LINK is left. Deliberately NOT symmetric with {@link shouldEmitDelete}
 * when it returns true — a staged UPDATE SURVIVES an emitted UNLINK, because
 * unlinking detaches a record that goes on existing, so an edit the user made
 * to it is a separate intent from the detachment. Pinned as a control by
 * audit_challenge_command_builder.test.js ("UNLINK without a LINK still emits
 * and keeps the UPDATE").
 *
 * @param {Array<{command: number[], index: number}>} ownCommands
 *     Existing commands for this record id. Pruned in place.
 * @returns {boolean} true if an UNLINK command should be emitted
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
            ownCommands.splice(0);
        }
        return false;
    }
    return true;
}

/**
 * Check if an UNLINK should be absorbed by an existing SET command.
 *
 * When a SET command exists as the first command (from _replaceWith),
 * unlinking a record that's in the SET list just removes it from that list
 * rather than emitting a separate UNLINK.
 *
 * MUTATES ``allCommands`` when it absorbs: rewrites the SET's id list and
 * splices out that id's staged UPDATEs, so the save neither re-adds the record
 * nor writes into one the SET no longer contains.
 *
 * @param {Array<[number, any, any?]>} allCommands - the full command list,
 *     rewritten in place when the return value is true
 * @param {string|number} recordId - the id to unlink
 * @returns {boolean} true if the UNLINK was absorbed by the SET command
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
    for (let i = allCommands.length - 1; i > 0; i--) {
        if (allCommands[i][0] === UPDATE && allCommands[i][1] === recordId) {
            allCommands.splice(i, 1);
        }
    }
    return true;
}

/**
 * Check whether a duplicate UPDATE command should be skipped.
 *
 * If there's already a CREATE or UPDATE command for this record id,
 * a new UPDATE command is redundant (the record's data will be read
 * from the cache when serializing).
 *
 * @param {Array<{command: number[], index: number}>} ownCommands
 * @returns {boolean} true if the UPDATE is redundant and should be skipped
 */
export function isUpdateRedundant(ownCommands) {
    return ownCommands.some((x) => x.command[0] === CREATE || x.command[0] === UPDATE);
}
