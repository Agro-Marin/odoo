// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/static_list_command_engine */

import {
    absorbUnlinkIntoSet,
    isUpdateRedundant,
    shouldEmitDelete,
    shouldEmitUnlink,
} from "./command_builder.js";
import { x2ManyCommands } from "./commands.js";
import { getId, isX2Many } from "./field_context.js";

/** @import { StaticList } from "@web/model/relational_model/static_list" */

/**
 * @param {[number, any, any][]} commands
 * @returns {[number, any, any][]}
 */
function expandSetCommands(commands) {
    const { LINK, SET, CLEAR } = x2ManyCommands;
    if (!commands.some((command) => command[0] === SET)) {
        return commands;
    }
    /** @type {[number, any, any][]} */
    const expanded = [];
    for (const command of commands) {
        if (command[0] !== SET) {
            expanded.push(command);
            continue;
        }
        expanded.push([CLEAR, false, false]);
        for (const resId of command[2] || []) {
            expanded.push([LINK, resId, false]);
        }
    }
    return expanded;
}

/**
 * Removing an id that was also re-added in the same batch must strip the
 * STALE entry, not the new one: a re-LINK appends a second entry, so dropping
 * the first occurrence leaves the re-added row at its new position.
 *
 * `removedIds` counts *pending removals*, not "is removed": CLEAR-then-LINK-
 * then-UNLINK marks the same id twice and must drop both entries, which a
 * boolean flag cannot express.
 *
 * @template T
 * @param {T[]} items
 * @param {Record<string|number, number>} removedIds
 * @param {(item: T) => string | number} keyOf
 * @returns {T[]}
 */
function dropFirstOccurrences(items, removedIds, keyOf) {
    const pending = { ...removedIds };
    return items.filter((item) => {
        const key = keyOf(item);
        if (pending[key] > 0) {
            pending[key]--;
            return false;
        }
        return true;
    });
}

/**
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
    const { CREATE, UPDATE, DELETE, UNLINK, LINK, CLEAR } = x2ManyCommands;
    commands = expandSetCommands(commands);

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

    /** @type {Record<string|number, number>} */
    const removedIds = {};
    const currentIdsSet = new Set(list._currentIds);
    const recordsToLoad = [];
    const clearedIds = new Set();
    const readdedIds = new Set();

    /**
     * @param {string | number} id
     */
    function markRemoved(id) {
        removedIds[id] = (removedIds[id] || 0) + 1;
    }

    /**
     * @returns {number}
     */
    function pageOccupancy() {
        let occupancy = 0;
        for (const record of list.records) {
            if (!removedIds[record.resId || record._virtualId]) {
                occupancy++;
            }
        }
        return occupancy;
    }

    /**
     * @param {string | number} id
     * @returns {boolean}
     */
    function reviveClearedMember(id) {
        if (!clearedIds.has(id)) {
            return false;
        }
        clearedIds.delete(id);
        if (removedIds[id] > 0) {
            removedIds[id]--;
        }
        currentIdsSet.add(id);
        return true;
    }

    for (const command of commands) {
        switch (command[0]) {
            case CLEAR: {
                const hadContent =
                    list._currentIds.length > 0 ||
                    Object.keys(commandsByIds).length > 0;
                for (const id of list._currentIds) {
                    markRemoved(id);
                    clearedIds.add(id);
                    delete list._unknownRecordCommands[id];
                    list._loadingStubIds.delete(id);
                }
                currentIdsSet.clear();
                for (const key of Object.keys(commandsByIds)) {
                    delete commandsByIds[key];
                }
                if (hadContent) {
                    addOwnCommand([CLEAR, false, false]);
                }
                break;
            }
            case CREATE: {
                const echoedId = command[1];
                const isEcho = Boolean(echoedId) && echoedId in list._cache;
                const virtualId = isEcho ? echoedId : getId("virtual");
                let record;
                if (isEcho) {
                    record = list._cache[virtualId];
                    record._applyChanges({}, command[2]);
                } else {
                    record = list._createRecordDatapoint(command[2], { virtualId });
                }
                if (
                    !getOwnCommands(virtualId).some((own) => own.command[0] === CREATE)
                ) {
                    addOwnCommand([CREATE, virtualId]);
                }
                if (reviveClearedMember(virtualId) || currentIdsSet.has(virtualId)) {
                    break;
                }
                list.records.push(record);
                currentIdsSet.add(virtualId);
                const index = list.offset + list.limit;
                list._currentIds.splice(index, 0, virtualId);
                const occupancy = pageOccupancy();
                if (occupancy > list.limit) {
                    list._bumpLimit(occupancy - list.limit);
                }
                list.count++;
                break;
            }
            case UPDATE: {
                if (reviveClearedMember(command[1])) {
                    addOwnCommand(
                        typeof command[1] === "number"
                            ? [LINK, command[1], false]
                            : [CREATE, command[1]],
                    );
                }
                if (!isUpdateRedundant(getOwnCommands(command[1]))) {
                    addOwnCommand([UPDATE, command[1]]);
                }
                const record = list._cache[command[1]];
                if (!record) {
                    if (!(command[1] in list._unknownRecordCommands)) {
                        list._unknownRecordCommands[command[1]] = [];
                    }
                    list._unknownRecordCommands[command[1]].push(command);
                } else if (
                    command[1] in list._unknownRecordCommands &&
                    list._loadingStubIds.has(command[1])
                ) {
                    list._unknownRecordCommands[command[1]].push(command);
                } else {
                    const changes = {};
                    /** @type {Record<string, any> | null} */
                    let deferredChanges = null;
                    for (const fieldName of Object.keys(command[2])) {
                        if (isX2Many(list.fields[fieldName])) {
                            const invisible = record.activeFields[fieldName]?.invisible;
                            if (
                                invisible === "True" ||
                                invisible === "1" ||
                                !(fieldName in record.activeFields)
                            ) {
                                deferredChanges = deferredChanges || {};
                                deferredChanges[fieldName] = command[2][fieldName];
                                continue;
                            }
                        }
                        changes[fieldName] = command[2][fieldName];
                    }
                    if (deferredChanges) {
                        if (!(command[1] in list._unknownRecordCommands)) {
                            list._unknownRecordCommands[command[1]] = [];
                        }
                        list._unknownRecordCommands[command[1]].push([
                            command[0],
                            command[1],
                            deferredChanges,
                        ]);
                    }
                    record._applyChanges({}, changes);
                }
                break;
            }
            case DELETE:
            case UNLINK: {
                const absorbedIntoSet =
                    command[0] === UNLINK &&
                    absorbUnlinkIntoSet(list._commands, command[1]);
                if (absorbedIntoSet) {
                    getOwnCommands(command[1]).splice(0);
                } else {
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
                }
                markRemoved(command[1]);
                readdedIds.delete(command[1]);
                delete list._unknownRecordCommands[command[1]];
                list._loadingStubIds.delete(command[1]);
                break;
            }
            case LINK: {
                let record;
                const wasCached = command[1] in list._cache;
                const needsLoad =
                    !wasCached || list._getResIdsToLoad([command[1]]).length > 0;
                if (wasCached) {
                    record = list._cache[command[1]];
                } else {
                    record = list._createRecordDatapoint({
                        ...command[2],
                        id: command[1],
                    });
                }
                if (
                    currentIdsSet.has(record.resId) &&
                    (!removedIds[record.resId] || readdedIds.has(record.resId))
                ) {
                    break;
                }
                readdedIds.add(record.resId);
                clearedIds.delete(record.resId);
                const displayed =
                    !list.limit || list.records.length < list.limit || canAddOverLimit;
                if (displayed) {
                    if (!command[2] && needsLoad) {
                        recordsToLoad.push(record);
                    }
                    list.records.push(record);
                    const occupancy = pageOccupancy();
                    if (occupancy > list.limit) {
                        list._bumpLimit(occupancy - list.limit);
                    }
                    list._currentIds.splice(
                        list.offset + list.records.length - 1,
                        0,
                        record.resId,
                    );
                } else {
                    list._currentIds.push(record.resId);
                }
                currentIdsSet.add(record.resId);
                addOwnCommand([command[0], command[1], false]);
                list.count++;
                break;
            }
            default: {
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

    if (Object.keys(removedIds).length) {
        let removedBeforeOffset = 0;
        for (const id of list._currentIds.slice(0, list.offset)) {
            if (removedIds[id]) {
                removedBeforeOffset++;
            }
        }
        if (removedBeforeOffset) {
            list.model._patchConfig(list.config, {
                offset: Math.max(0, list.offset - removedBeforeOffset),
            });
        }
        list.records = dropFirstOccurrences(
            list.records,
            removedIds,
            (record) =>
                /** @type {string | number} */ (record.resId || record._virtualId),
        );
        list._currentIds = dropFirstOccurrences(
            list._currentIds,
            removedIds,
            (id) => id,
        );
        list.count = list._currentIds.length;
    }

    list._clampOffset();

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
            list._loadingStubIds.add(id);
            recordsToLoad.push(record);
        }
        for (const id of nextRecordIds) {
            if (list._cache[id]) {
                list.records.push(list._cache[id]);
            }
        }
    }
    if (recordsToLoad.length) {
        const resIds = recordsToLoad.map((r) => r.resId);
        return list.model
            ._loadRecords({ ...list.config, resIds }, list.evalContext)
            .then(async (recordValues) => {
                const valuesById = Object.fromEntries(
                    recordValues.map((v) => [v.id, v]),
                );
                for (const record of recordsToLoad) {
                    if (!valuesById[record.resId]) {
                        list._loadingStubIds.delete(record.resId);
                        continue;
                    }
                    record._applyValues(valuesById[record.resId]);
                    list._loadingStubIds.delete(record.resId);
                    const commands = list._unknownRecordCommands[record.resId];
                    if (commands) {
                        delete list._unknownRecordCommands[record.resId];
                        await applyCommands(list, commands);
                    }
                }
            });
    }
}
