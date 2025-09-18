// @ts-check

/** @module @web/model/relational_model/static_list_command_engine - Command application logic extracted from StaticList */

/**
 * Processes x2many ORM commands (CREATE, UPDATE, DELETE, UNLINK, LINK)
 * on a StaticList instance. Manages the command log, record cache,
 * and currentIds list.
 *
 * Receives the StaticList instance as first argument (delegation pattern).
 */

import { x2ManyCommands } from "./commands";
import {
    absorbUnlinkIntoSet,
    isUpdateRedundant,
    shouldEmitDelete,
    shouldEmitUnlink,
} from "./command_builder";
import { getId } from "./field_context";

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

    // For performance reasons, we split commands by record ids, such that we have quick access
    // to all commands concerning a given record. At the end, we re-build the list of commands
    // from this structure.
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

    // For performance reasons, we accumulate removed ids (commands DELETE and UNLINK), and at
    // the end, we filter once list.records and list._currentIds to remove them.
    const removedIds = {};
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
                list._tmpIncreaseLimit = Math.max(
                    list.records.length - list.limit,
                    0,
                );
                const nextLimit = list.limit + list._tmpIncreaseLimit;
                list.model._updateConfig(
                    list.config,
                    { limit: nextLimit },
                    { reload: false },
                );
                list.count++;
                break;
            }
            case UPDATE: {
                if (!isUpdateRedundant(getOwnCommands(command[1]))) {
                    addOwnCommand([UPDATE, command[1]]);
                }
                const record = list._cache[command[1]];
                if (!record) {
                    // the record isn't in the cache, it means it is on a page we haven't loaded
                    // so we say the record is "unknown", and store all update commands we
                    // receive about it in a separated structure, s.t. we can easily apply them
                    // later on after loading the record, if we ever load it.
                    if (!(command[1] in list._unknownRecordCommands)) {
                        list._unknownRecordCommands[command[1]] = [];
                    }
                    list._unknownRecordCommands[command[1]].push(command);
                } else if (command[1] in list._unknownRecordCommands) {
                    // this case is more tricky: the record is in the cache, but it isn't loaded
                    // yet, as we are currently loading it (see below, where we load missing
                    // records for the current page)
                    list._unknownRecordCommands[command[1]].push(command);
                } else {
                    const changes = {};
                    for (const fieldName in command[2]) {
                        if (
                            ["one2many", "many2many"].includes(
                                list.fields[fieldName].type,
                            )
                        ) {
                            const invisible =
                                record.activeFields[fieldName]?.invisible;
                            if (
                                invisible === "True" ||
                                invisible === "1" ||
                                !(fieldName in record.activeFields) // this record hasn't been extended
                            ) {
                                if (!(command[1] in list._unknownRecordCommands)) {
                                    list._unknownRecordCommands[command[1]] = [];
                                }
                                list._unknownRecordCommands[command[1]].push(
                                    command,
                                );
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
                        addOwnCommand([DELETE, command[1]]);
                    }
                } else {
                    if (shouldEmitUnlink(ownCommands)) {
                        addOwnCommand([UNLINK, command[1]]);
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
                if (
                    list._currentIds.includes(record.resId) &&
                    !removedIds[record.resId]
                ) {
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
                        list._tmpIncreaseLimit = list.records.length - list.limit;
                        const nextLimit = list.limit + list._tmpIncreaseLimit;
                        list.model._updateConfig(
                            list.config,
                            { limit: nextLimit },
                            { reload: false },
                        );
                    }
                }
                list._currentIds.push(record.resId);
                addOwnCommand([command[0], command[1]]);
                list.count++;
                break;
            }
        }
    }

    // Re-generate the new list of commands
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

    // Fill the page if it isn't full w.r.t. the limit. This may happen if we aren't on the last
    // page and records of the current have been removed, or if we applied commands to remove
    // some records and to add others, but we were on the limit.
    const nbMissingRecords = list.limit - list.records.length;
    if (nbMissingRecords > 0) {
        const lastRecordIndex = list.limit + list.offset;
        const firstRecordIndex = lastRecordIndex - nbMissingRecords;
        const nextRecordIds = list._currentIds.slice(
            firstRecordIndex,
            lastRecordIndex,
        );
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
            .then((recordValues) => {
                for (let i = 0; i < recordsToLoad.length; i++) {
                    const record = recordsToLoad[i];
                    record._applyValues(recordValues[i]);
                    const commands = list._unknownRecordCommands[record.resId];
                    if (commands) {
                        delete list._unknownRecordCommands[record.resId];
                        applyCommands(list, commands);
                    }
                }
            });
    }
}
