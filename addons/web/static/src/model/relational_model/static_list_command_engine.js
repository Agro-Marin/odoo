// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/static_list_command_engine - Command application logic extracted from StaticList */

/**
 * Processes x2many ORM commands (CREATE, UPDATE, DELETE, UNLINK, LINK)
 * on a StaticList instance. Manages the command log, record cache,
 * and currentIds list.
 *
 * Receives the StaticList instance as first argument (delegation pattern).
 */

import {
    absorbUnlinkIntoSet,
    isUpdateRedundant,
    shouldEmitDelete,
    shouldEmitUnlink,
} from "./command_builder.js";
import { x2ManyCommands } from "./commands.js";
import { getId } from "./field_context.js";

/** @import { StaticList } from "@web/model/relational_model/static_list" */

/**
 * Apply a sequence of x2many commands to the list.
 *
 * Splits commands by record id for efficient lookup, handles CREATE/UPDATE/DELETE/UNLINK/LINK,
 * rebuilds the command log, filters removed records, and fills the page if needed.
 *
 * @param {StaticList} list
 * @param {[number, any, any][]} commands
 * @param {{ canAddOverLimit?: boolean }} [options]
 * @returns {Promise<void> | undefined}
 */
export function applyCommands(
    list,
    commands,
    /** @type {{ canAddOverLimit?: boolean }} */ { canAddOverLimit } = {},
) {
    const { CREATE, UPDATE, DELETE, UNLINK, LINK } = x2ManyCommands;

    // Split commands by record id for O(1) lookup; re-built into the final list below.
    let lastCommandIndex = -1;
    const commandsByIds = {};
    function addOwnCommand(command) {
        commandsByIds[command[1]] = commandsByIds[command[1]] || [];
        commandsByIds[command[1]].push({
            command,
            index: ++lastCommandIndex,
        });
    }
    function getOwnCommands(id) {
        commandsByIds[id] = commandsByIds[id] || [];
        return commandsByIds[id];
    }
    for (const command of list._commands) {
        addOwnCommand(command);
    }

    // Accumulate removed ids (DELETE/UNLINK) and filter records/_currentIds once at the end.
    const removedIds = {};
    const currentIdsSet = new Set(list._currentIds);
    const recordsToLoad = [];
    for (const command of commands) {
        switch (command[0]) {
            case CREATE: {
                const virtualId = getId("virtual");
                const record = list._createRecordDatapoint(command[2], {
                    virtualId,
                });
                list.records.push(record);
                addOwnCommand([CREATE, virtualId]);
                const index = list.offset + list.limit;
                list._currentIds.splice(index, 0, virtualId);
                if (list.records.length > list.limit) {
                    list._bumpLimit(list.records.length - list.limit);
                }
                list.count++;
                break;
            }
            case UPDATE: {
                if (!isUpdateRedundant(getOwnCommands(command[1]))) {
                    addOwnCommand([UPDATE, command[1]]);
                }
                const record = list._cache[command[1]];
                if (!record) {
                    // Record is on an unloaded page: mark it "unknown" and stash update
                    // commands to replay later if it's ever loaded.
                    if (!(command[1] in list._unknownRecordCommands)) {
                        list._unknownRecordCommands[command[1]] = [];
                    }
                    list._unknownRecordCommands[command[1]].push(command);
                } else if (command[1] in list._unknownRecordCommands) {
                    // Record is cached but still loading (see the page-fill load below);
                    // keep stashing updates until it lands.
                    list._unknownRecordCommands[command[1]].push(command);
                } else {
                    const changes = {};
                    for (const fieldName of Object.keys(command[2])) {
                        if (
                            ["one2many", "many2many"].includes(
                                list.fields[fieldName].type,
                            )
                        ) {
                            const invisible = record.activeFields[fieldName]?.invisible;
                            if (
                                invisible === "True" ||
                                invisible === "1" ||
                                !(fieldName in record.activeFields) // this record hasn't been extended
                            ) {
                                if (!(command[1] in list._unknownRecordCommands)) {
                                    list._unknownRecordCommands[command[1]] = [];
                                }
                                list._unknownRecordCommands[command[1]].push(command);
                                continue;
                            }
                        }
                        changes[fieldName] = command[2][fieldName];
                    }
                    record._applyChanges(
                        record._parseServerValues(changes, {
                            currentValues: record.data,
                        }),
                    );
                }
                break;
            }
            case DELETE:
            case UNLINK: {
                if (
                    command[0] === UNLINK &&
                    absorbUnlinkIntoSet(list._commands, command[1])
                ) {
                    break;
                }
                const ownCommands = getOwnCommands(command[1]);
                if (command[0] === DELETE) {
                    if (shouldEmitDelete(ownCommands)) {
                        addOwnCommand([DELETE, command[1], false]);
                    }
                } else {
                    if (shouldEmitUnlink(ownCommands)) {
                        addOwnCommand([UNLINK, command[1], false]);
                    }
                }
                removedIds[command[1]] = true;
                break;
            }
            case LINK: {
                let record;
                if (command[1] in list._cache) {
                    record = list._cache[command[1]];
                } else {
                    record = list._createRecordDatapoint({
                        ...command[2],
                        id: command[1],
                    });
                }
                if (currentIdsSet.has(record.resId) && !removedIds[record.resId]) {
                    break;
                }
                if (
                    !list.limit ||
                    list.records.length < list.limit ||
                    canAddOverLimit
                ) {
                    if (!command[2]) {
                        recordsToLoad.push(record);
                    }
                    list.records.push(record);
                    if (list.records.length > list.limit) {
                        list._bumpLimit(list.records.length - list.limit);
                    }
                }
                list._currentIds.push(record.resId);
                currentIdsSet.add(record.resId);
                addOwnCommand([command[0], command[1], false]);
                list.count++;
                break;
            }
            default: {
                // SET (6) / CLEAR (5) are routed around the engine in normal
                // flows (preprocessX2manyChanges → _replaceWith), but raw
                // server command lists (parseServerValues, initial commands)
                // land here — surface a protocol drift loudly instead of
                // silently keeping stale rows.
                console.warn(
                    `applyCommands: unhandled x2many command ${command[0]} on ${list.resModel}; command ignored`,
                );
                break;
            }
        }
    }

    list._commands = Object.values(commandsByIds)
        .flat()
        .sort((x, y) => x.index - y.index)
        .map((x) => x.command);

    // Filter out removed records and ids from list.records and list._currentIds
    if (Object.keys(removedIds).length) {
        let removeCommandsByIdsCopy = { ...removedIds };
        list.records = list.records.filter((r) => {
            const id = /** @type {string | number} */ (r.resId || r._virtualId);
            if (removeCommandsByIdsCopy[id]) {
                delete removeCommandsByIdsCopy[id];
                return false;
            }
            return true;
        });
        const nextCurrentIds = [];
        removeCommandsByIdsCopy = { ...removedIds };
        for (const id of list._currentIds) {
            if (removeCommandsByIdsCopy[id]) {
                delete removeCommandsByIdsCopy[id];
            } else {
                nextCurrentIds.push(id);
            }
        }
        list._currentIds = nextCurrentIds;
        list.count = list._currentIds.length;
    }

    // Fill the page if it's below the limit — can happen when records were removed while not
    // on the last page, or when removals/additions land exactly at the limit.
    const nbMissingRecords = list.limit - list.records.length;
    if (nbMissingRecords > 0) {
        const lastRecordIndex = list.limit + list.offset;
        const firstRecordIndex = lastRecordIndex - nbMissingRecords;
        const nextRecordIds = list._currentIds.slice(firstRecordIndex, lastRecordIndex);
        for (const id of list._getResIdsToLoad(nextRecordIds)) {
            const record = list._createRecordDatapoint(
                { id },
                { dontApplyCommands: true },
            );
            recordsToLoad.push(record);
        }
        for (const id of nextRecordIds) {
            list.records.push(list._cache[id]);
        }
    }
    if (recordsToLoad.length) {
        const resIds = recordsToLoad.map((r) => r.resId);
        return list.model
            ._loadRecords({ ...list.config, resIds })
            .then(async (recordValues) => {
                const valuesById = Object.fromEntries(
                    recordValues.map((v) => [v.id, v]),
                );
                for (const record of recordsToLoad) {
                    if (!valuesById[record.resId]) {
                        // The server returned fewer records than requested
                        // (e.g. concurrently deleted): never fall back to
                        // index-based access, as that would merge ANOTHER
                        // record's values (id included) into this record.
                        continue;
                    }
                    record._applyValues(valuesById[record.resId]);
                    const commands = list._unknownRecordCommands[record.resId];
                    if (commands) {
                        delete list._unknownRecordCommands[record.resId];
                        // await so the outer promise doesn't resolve before the
                        // recursive application completes (and so rejections
                        // propagate instead of being unhandled)
                        await applyCommands(list, commands);
                    }
                }
            });
    }
}
