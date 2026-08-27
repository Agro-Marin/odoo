// @ts-check
/** @odoo-module native */

import { isX2Many } from "@web/core/field_types";
import { x2ManyCommands } from "@web/core/network/commands";

import {
    absorbUnlinkIntoSet,
    isUpdateRedundant,
    reconcileDelete,
    reconcileUnlink,
} from "./command_builder.js";
import { getId } from "./field_context.js";
import { listId } from "./static_list_utils.js";

/** @import { X2ManyCommand } from "@web/core/network/commands" */
/** @import { LedgerEntry } from "./command_builder.js" */
/** @import { StaticListInternals } from "./static_list_contract.js" */

/**
 * @typedef {{
 * addOwnCommand: (command: X2ManyCommand, index?: number) => void;
 * getOwnCommands: (id: string | number) => LedgerEntry[];
 * dropOwnCommands: (id: string | number) => void;
 * clearOwnCommands: () => void;
 * hasOwnCommands: () => boolean;
 * orderedCommands: () => X2ManyCommand[];
 * topInsertIndex: number;
 * }} CommandLedger
 * @typedef {CommandLedger & {
 * markRemoved: (id: string | number) => void;
 * pageOccupancy: () => number;
 * reviveClearedMember: (id: string | number) => boolean;
 * removedIds: Record<string | number, number>;
 * currentIdsSet: Set<any>;
 * clearedIds: Set<any>;
 * readdedIds: Set<any>;
 * recordsToLoad: any[];
 * canAddOverLimit: boolean | undefined;
 * position: "top" | "bottom" | undefined;
 * }} CommandBatch
 */

/**
 * @param {X2ManyCommand[]} commands
 * @returns {X2ManyCommand[]}
 */
function expandSetCommands(commands) {
    const { LINK, SET, CLEAR } = x2ManyCommands;
    if (!commands.some((command) => command[0] === SET)) {
        return commands;
    }
    /** @type {X2ManyCommand[]} */
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
 * @param {X2ManyCommand[]} seedCommands
 * @returns {CommandLedger}
 */
function createCommandLedger(seedCommands) {
    const { SET, CLEAR } = x2ManyCommands;
    let lastCommandIndex = -1;
    /** @type {Record<string | number, LedgerEntry[]>} */
    const commandsByIds = {};
    const ledger = {
        topInsertIndex: -0.5,
        addOwnCommand(command, index) {
            commandsByIds[command[1]] = commandsByIds[command[1]] || [];
            commandsByIds[command[1]].push({
                command,
                index: index ?? ++lastCommandIndex,
            });
        },
        getOwnCommands(id) {
            commandsByIds[id] = commandsByIds[id] || [];
            return commandsByIds[id];
        },
        dropOwnCommands(id) {
            ledger.getOwnCommands(id).splice(0);
        },
        clearOwnCommands() {
            for (const key of Object.keys(commandsByIds)) {
                delete commandsByIds[key];
            }
        },
        hasOwnCommands() {
            return Object.keys(commandsByIds).length > 0;
        },
        orderedCommands() {
            return Object.values(commandsByIds)
                .flat()
                .sort((x, y) => x.index - y.index)
                .map((x) => x.command);
        },
    };
    let prefixOpen = true;
    for (const command of seedCommands) {
        ledger.addOwnCommand(command);
        if (prefixOpen && (command[0] === SET || command[0] === CLEAR)) {
            ledger.topInsertIndex += 1;
        } else {
            prefixOpen = false;
        }
    }
    return ledger;
}

/**
 * @param {StaticListInternals} list
 * @param {{ canAddOverLimit?: boolean, position?: "top" | "bottom" }} options
 * @returns {CommandBatch}
 */
function createCommandBatch(list, { canAddOverLimit, position }) {
    /** @type {Record<string | number, number>} */
    const removedIds = {};
    const currentIdsSet = new Set(list._currentIds);
    const clearedIds = new Set();
    const readdedIds = new Set();
    const recordsToLoad = [];

    return {
        ...createCommandLedger(list._commands),
        removedIds,
        currentIdsSet,
        clearedIds,
        readdedIds,
        recordsToLoad,
        canAddOverLimit,
        position,
        markRemoved(id) {
            removedIds[id] = (removedIds[id] || 0) + 1;
        },
        pageOccupancy() {
            let occupancy = 0;
            for (const record of list.records) {
                if (!removedIds[listId(record)]) {
                    occupancy++;
                }
            }
            return occupancy;
        },
        reviveClearedMember(id) {
            if (!clearedIds.has(id)) {
                return false;
            }
            clearedIds.delete(id);
            if (removedIds[id] > 0) {
                removedIds[id]--;
            }
            currentIdsSet.add(id);
            return true;
        },
    };
}

/**
 * @param {StaticListInternals} list
 * @param {CommandBatch} batch
 * @returns {void}
 */
function applyClear(list, batch) {
    const { CLEAR } = x2ManyCommands;
    const hadContent = list._currentIds.length > 0 || batch.hasOwnCommands();
    for (const id of list._currentIds) {
        batch.markRemoved(id);
        batch.clearedIds.add(id);
        list._unknownRecordCommands.delete(id);
        list._loadingStubIds.delete(id);
    }
    batch.currentIdsSet.clear();
    batch.clearOwnCommands();
    if (hadContent) {
        batch.addOwnCommand([CLEAR, false, false]);
    }
}

/**
 * @param {StaticListInternals} list
 * @param {X2ManyCommand} command
 * @param {CommandBatch} batch
 * @returns {void}
 */
function applyCreate(list, command, batch) {
    const { CREATE } = x2ManyCommands;
    const echoedId = command[1];
    const isEcho = Boolean(echoedId) && list._cache.has(echoedId);
    const virtualId = isEcho ? echoedId : getId("virtual");
    let record;
    if (isEcho) {
        record = list._cache.get(virtualId);
        record._applyChanges({}, command[2]);
    } else {
        record = list._createRecordDatapoint(command[2], { virtualId });
    }
    if (!batch.getOwnCommands(virtualId).some((own) => own.command[0] === CREATE)) {
        const at = batch.position === "top" ? batch.topInsertIndex : undefined;
        batch.addOwnCommand([CREATE, virtualId], at);
    }
    if (batch.reviveClearedMember(virtualId) || batch.currentIdsSet.has(virtualId)) {
        return;
    }
    batch.currentIdsSet.add(virtualId);
    const atTop = batch.position === "top";
    if (atTop) {
        list.records.unshift(record);
    } else {
        list.records.push(record);
    }
    list._insertMemberAt(atTop ? list.offset : list.offset + list.limit, virtualId);
    if (atTop) {
        if (list.records.length > list.limit) {
            list.records.pop();
        }
    } else {
        const occupancy = batch.pageOccupancy();
        if (occupancy > list.limit) {
            list._bumpLimit(occupancy - list.limit);
        }
    }
}

/**
 * @param {StaticListInternals} list
 * @param {any} record
 * @param {Record<string, any>} values
 * @returns {{ changes: Record<string, any>, deferredChanges: Record<string, any> | null }}
 */
function partitionUpdateChanges(list, record, values) {
    const changes = {};
    /** @type {Record<string, any> | null} */
    let deferredChanges = null;
    for (const fieldName of Object.keys(values)) {
        if (isX2Many(list.fields[fieldName])) {
            const invisible = record.activeFields[fieldName]?.invisible;
            if (
                invisible === "True" ||
                invisible === "1" ||
                !(fieldName in record.activeFields)
            ) {
                deferredChanges = deferredChanges || {};
                deferredChanges[fieldName] = values[fieldName];
                continue;
            }
        }
        changes[fieldName] = values[fieldName];
    }
    return { changes, deferredChanges };
}

/**
 * @param {StaticListInternals} list
 * @param {string | number} id
 * @param {X2ManyCommand} command
 * @returns {void}
 */
function deferCommand(list, id, command) {
    const deferred = list._unknownRecordCommands.get(id);
    if (deferred) {
        deferred.push(command);
    } else {
        list._unknownRecordCommands.set(id, [command]);
    }
}

/**
 * @param {StaticListInternals} list
 * @param {X2ManyCommand} command
 * @param {CommandBatch} batch
 * @returns {void}
 */
function applyUpdate(list, command, batch) {
    const { CREATE, UPDATE, LINK } = x2ManyCommands;
    const id = command[1];
    if (batch.reviveClearedMember(id)) {
        batch.addOwnCommand(typeof id === "number" ? [LINK, id, false] : [CREATE, id]);
    }
    if (!isUpdateRedundant(batch.getOwnCommands(id))) {
        batch.addOwnCommand([UPDATE, id]);
    }
    const record = list._cache.get(id);
    if (!record) {
        deferCommand(list, id, command);
        return;
    }
    if (list._unknownRecordCommands.has(id) && list._loadingStubIds.has(id)) {
        deferCommand(list, id, command);
        return;
    }
    const { changes, deferredChanges } = partitionUpdateChanges(
        list,
        record,
        command[2],
    );
    if (deferredChanges) {
        deferCommand(list, id, [command[0], id, deferredChanges]);
    }
    record._applyChanges({}, changes);
}

/**
 * @param {StaticListInternals} list
 * @param {X2ManyCommand} command
 * @param {CommandBatch} batch
 * @returns {void}
 */
function applyRemoval(list, command, batch) {
    const { DELETE, UNLINK } = x2ManyCommands;
    const id = command[1];
    const absorbedIntoSet =
        command[0] === UNLINK && absorbUnlinkIntoSet(list._commands, id);
    if (absorbedIntoSet) {
        batch.dropOwnCommands(id);
    } else {
        const ownCommands = batch.getOwnCommands(id);
        if (command[0] === DELETE) {
            if (reconcileDelete(ownCommands)) {
                batch.addOwnCommand([DELETE, id, false]);
            }
        } else if (reconcileUnlink(ownCommands)) {
            batch.addOwnCommand([UNLINK, id, false]);
        }
    }
    batch.markRemoved(id);
    batch.readdedIds.delete(id);
    list._unknownRecordCommands.delete(id);
    list._loadingStubIds.delete(id);
}

/**
 * @param {StaticListInternals} list
 * @param {X2ManyCommand} command
 * @param {CommandBatch} batch
 * @returns {void}
 */
function applyLink(list, command, batch) {
    let record;
    const wasCached = list._cache.has(command[1]);
    if (wasCached) {
        record = list._cache.get(command[1]);
    } else {
        record = list._createRecordDatapoint({ ...command[2], id: command[1] });
    }
    const needsLoad = !wasCached || list._getResIdsToLoad([command[1]]).length > 0;
    if (
        batch.currentIdsSet.has(record.resId) &&
        (!batch.removedIds[record.resId] || batch.readdedIds.has(record.resId))
    ) {
        return;
    }
    batch.readdedIds.add(record.resId);
    batch.clearedIds.delete(record.resId);
    const displayed =
        !list.limit || list.records.length < list.limit || batch.canAddOverLimit;
    if (displayed) {
        if (!command[2] && needsLoad) {
            batch.recordsToLoad.push(record);
        }
        list.records.push(record);
        const occupancy = batch.pageOccupancy();
        if (occupancy > list.limit) {
            list._bumpLimit(occupancy - list.limit);
        }
        list._insertMemberAt(list.offset + list.records.length - 1, record.resId);
    } else {
        list._appendMember(record.resId);
    }
    batch.currentIdsSet.add(record.resId);
    batch.addOwnCommand([command[0], command[1], false]);
}

/**
 * @param {StaticListInternals} list
 * @param {CommandBatch} batch
 * @returns {void}
 */
function commitBatch(list, batch) {
    list._commitCommands(batch.orderedCommands());

    if (Object.keys(batch.removedIds).length) {
        let removedBeforeOffset = 0;
        for (const id of list._currentIds.slice(0, list.offset)) {
            if (batch.removedIds[id]) {
                removedBeforeOffset++;
            }
        }
        if (removedBeforeOffset) {
            list.model._patchConfig(list.config, {
                offset: Math.max(0, list.offset - removedBeforeOffset),
            });
        }
        list.records = dropFirstOccurrences(list.records, batch.removedIds, listId);
        list._commitCurrentIds(
            dropFirstOccurrences(list._currentIds, batch.removedIds, (id) => id),
        );
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
            batch.recordsToLoad.push(record);
        }
        for (const id of nextRecordIds) {
            const cached = list._cache.get(id);
            if (cached) {
                list.records.push(cached);
            }
        }
    }
}

/**
 * @param {StaticListInternals} list
 * @param {CommandBatch} batch
 * @returns {Promise<void> | undefined}
 */
function flushPendingLoads(list, batch) {
    if (!batch.recordsToLoad.length) {
        return undefined;
    }
    const resIds = batch.recordsToLoad.map((r) => r.resId);
    return list.model
        ._loadRecords({ ...list.config, resIds }, list.evalContext)
        .then(async (recordValues) => {
            const valuesById = Object.fromEntries(recordValues.map((v) => [v.id, v]));
            for (const record of batch.recordsToLoad) {
                if (!valuesById[record.resId]) {
                    list._loadingStubIds.delete(record.resId);
                    continue;
                }
                record._applyValues(valuesById[record.resId]);
                list._loadingStubIds.delete(record.resId);
                const commands = list._unknownRecordCommands.get(record.resId);
                if (commands) {
                    list._unknownRecordCommands.delete(record.resId);
                    await applyCommands(list, commands);
                }
            }
        });
}

/**
 * @param {StaticListInternals} list
 * @param {X2ManyCommand[]} commands
 * @param {{ canAddOverLimit?: boolean }} [options]
 * @returns {Promise<void> | undefined}
 */
export function applyCommands(
    list,
    commands,
    /** @type {{ canAddOverLimit?: boolean, position?: "top" | "bottom" }} */ {
        canAddOverLimit,
        position,
    } = {},
) {
    const { CREATE, UPDATE, DELETE, UNLINK, LINK, CLEAR } = x2ManyCommands;
    const batch = createCommandBatch(list, { canAddOverLimit, position });

    for (const command of expandSetCommands(commands)) {
        switch (command[0]) {
            case CLEAR:
                applyClear(list, batch);
                break;
            case CREATE:
                applyCreate(list, command, batch);
                break;
            case UPDATE:
                applyUpdate(list, command, batch);
                break;
            case DELETE:
            case UNLINK:
                applyRemoval(list, command, batch);
                break;
            case LINK:
                applyLink(list, command, batch);
                break;
            default:
                console.warn(
                    `applyCommands: unhandled x2many command ${command[0]} on ${list.resModel}; command ignored`,
                );
                break;
        }
    }

    commitBatch(list, batch);
    return flushPendingLoads(list, batch);
}
