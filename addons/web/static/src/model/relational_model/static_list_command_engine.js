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
import { listId } from "./static_list_utils.js";

/** @import { StaticList } from "@web/model/relational_model/static_list" */

/**
 * An x2many command tuple `[code, id, values?]`. The third element is optional:
 * DELETE/UNLINK/CLEAR and an echoed CREATE carry only `[code, id]`, while
 * UPDATE/LINK/SET carry a payload. Typing it as a fixed 3-tuple rejected the
 * many `[code, id]` literals that are perfectly valid commands.
 * @typedef {[number, any, any?]} X2ManyCommand
 */

/**
 * The mutable state one `applyCommands` pass accumulates before any of it is
 * written back to the list. The per-command handlers below all read and write
 * it, which is why they take it rather than closing over it: as one 325-line
 * function the sharing was invisible, and every handler appeared to have the
 * whole list and the whole batch in scope whether it used them or not.
 *
 * @typedef {{
 *  addOwnCommand: (command: [number, any, any?], index?: number) => void;
 *  getOwnCommands: (id: string | number) => { command: [number, any, any?], index: number }[];
 *  dropOwnCommands: (id: string | number) => void;
 *  clearOwnCommands: () => void;
 *  hasOwnCommands: () => boolean;
 *  orderedCommands: () => [number, any, any?][];
 *  topInsertIndex: number;
 * }} CommandLedger
 *
 * @typedef {CommandLedger & {
 *  markRemoved: (id: string | number) => void;
 *  pageOccupancy: () => number;
 *  reviveClearedMember: (id: string | number) => boolean;
 *  removedIds: Record<string | number, number>;
 *  currentIdsSet: Set<any>;
 *  clearedIds: Set<any>;
 *  readdedIds: Set<any>;
 *  recordsToLoad: any[];
 *  canAddOverLimit: boolean | undefined;
 *  position: "top" | "bottom" | undefined;
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
 * The append-only command ledger for one pass: it records the per-id commands
 * (deduping and reordering happen through the `*OwnCommands` helpers), replays
 * the list's existing log by seeding from `seedCommands`, and precomputes
 * `topInsertIndex` -- the ordering index a top-position CREATE must use so it
 * lands after any leading SET/CLEAR but before every other command. A fractional
 * index threads that CREATE between two seeded neighbours (see `orderedCommands`)
 * without renumbering them.
 *
 * @param {[number, any, any?][]} seedCommands
 * @returns {CommandLedger}
 */
function createCommandLedger(seedCommands) {
    const { SET, CLEAR } = x2ManyCommands;
    let lastCommandIndex = -1;
    /** @type {Record<string | number, { command: [number, any, any?], index: number }[]>} */
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
 * @param {StaticList} list
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
        // Insertion position for CREATE, threaded from `_addRecord`. Absent for
        // command replay (onchange/link) -> bottom-of-window.
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
 * @param {StaticList} list
 * @param {CommandBatch} batch
 * @returns {void}
 */
function applyClear(list, batch) {
    const { CLEAR } = x2ManyCommands;
    const hadContent = list._currentIds.length > 0 || batch.hasOwnCommands();
    for (const id of list._currentIds) {
        batch.markRemoved(id);
        batch.clearedIds.add(id);
        delete list._unknownRecordCommands[id];
        list._loadingStubIds.delete(id);
    }
    batch.currentIdsSet.clear();
    batch.clearOwnCommands();
    if (hadContent) {
        batch.addOwnCommand([CLEAR, false, false]);
    }
}

/**
 * @param {StaticList} list
 * @param {X2ManyCommand} command
 * @param {CommandBatch} batch
 * @returns {void}
 */
function applyCreate(list, command, batch) {
    const { CREATE } = x2ManyCommands;
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
    if (!batch.getOwnCommands(virtualId).some((own) => own.command[0] === CREATE)) {
        const at = batch.position === "top" ? batch.topInsertIndex : undefined;
        batch.addOwnCommand([CREATE, virtualId], at);
    }
    if (batch.reviveClearedMember(virtualId) || batch.currentIdsSet.has(virtualId)) {
        return;
    }
    batch.currentIdsSet.add(virtualId);
    // Interactive top-add leads the window; bottom-add and command replay append
    // at the window's end. Both share one `_currentIds` insertion, differing only
    // in the index and in how a full page is handled.
    const atTop = batch.position === "top";
    if (atTop) {
        list.records.unshift(record);
    } else {
        list.records.push(record);
    }
    list._currentIds.splice(
        atTop ? list.offset : list.offset + list.limit,
        0,
        virtualId,
    );
    if (atTop) {
        // A full page drops its last row rather than growing (the limit holds).
        if (list.records.length > list.limit) {
            list.records.pop();
        }
    } else {
        // Grow the limit to keep a row added over an already-full page.
        const occupancy = batch.pageOccupancy();
        if (occupancy > list.limit) {
            list._bumpLimit(occupancy - list.limit);
        }
    }
}

/**
 * Splits a command's changes into those the record can take now and those that
 * have to wait: an x2many field the record does not carry as an active field,
 * or carries as invisible, has no datapoint to apply them to yet.
 *
 * @param {StaticList} list
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
 * @param {StaticList} list
 * @param {string | number} id
 * @param {X2ManyCommand} command
 * @returns {void}
 */
function deferCommand(list, id, command) {
    if (!(id in list._unknownRecordCommands)) {
        list._unknownRecordCommands[id] = [];
    }
    list._unknownRecordCommands[id].push(command);
}

/**
 * @param {StaticList} list
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
    const record = list._cache[id];
    if (!record) {
        deferCommand(list, id, command);
        return;
    }
    if (id in list._unknownRecordCommands && list._loadingStubIds.has(id)) {
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
 * DELETE and UNLINK differ only in which command they emit; both drop the id
 * from the page and forget anything queued against it.
 *
 * @param {StaticList} list
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
            if (shouldEmitDelete(ownCommands)) {
                batch.addOwnCommand([DELETE, id, false]);
            }
        } else if (shouldEmitUnlink(ownCommands)) {
            batch.addOwnCommand([UNLINK, id, false]);
        }
    }
    batch.markRemoved(id);
    batch.readdedIds.delete(id);
    delete list._unknownRecordCommands[id];
    list._loadingStubIds.delete(id);
}

/**
 * @param {StaticList} list
 * @param {X2ManyCommand} command
 * @param {CommandBatch} batch
 * @returns {void}
 */
function applyLink(list, command, batch) {
    let record;
    const wasCached = command[1] in list._cache;
    if (wasCached) {
        record = list._cache[command[1]];
    } else {
        record = list._createRecordDatapoint({ ...command[2], id: command[1] });
    }
    // An inlined payload is AUTHORITATIVE: whoever sent the LINK decided what
    // this row needs, and the omitted fields are not re-read. `_multiSave`
    // relies on it -- it rewrites a many2many's LINKs to carry display_name
    // alone -- and so does every onchange that inlines a subset.
    //
    // The cost is that a payload omitting a field the list DOES render leaves
    // it at its default with nothing queued to fix it. Asking
    // `_getResIdsToLoad` instead (i.e. completing every partial payload) is not
    // the fix: it re-reads the whole tag list on any many2many_tags edit. If
    // this ever bites, narrow the question to fields that are actually
    // displayed rather than to the list's whole active set.
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
        list._currentIds.splice(list.offset + list.records.length - 1, 0, record.resId);
    } else {
        list._currentIds.push(record.resId);
    }
    batch.currentIdsSet.add(record.resId);
    batch.addOwnCommand([command[0], command[1], false]);
}

/**
 * Writes the batch back to the list: the replayable command log, the removals,
 * and whatever the page has to pull in to stay full afterwards.
 *
 * @param {StaticList} list
 * @param {CommandBatch} batch
 * @returns {void}
 */
function commitBatch(list, batch) {
    list._commands = batch.orderedCommands();

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
        list._currentIds = dropFirstOccurrences(
            list._currentIds,
            batch.removedIds,
            (id) => id,
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
            if (list._cache[id]) {
                list.records.push(list._cache[id]);
            }
        }
    }
}

/**
 * Fetches the records the batch could not resolve locally and replays whatever
 * was deferred against them, which can enqueue further commands.
 *
 * @param {StaticList} list
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
                const commands = list._unknownRecordCommands[record.resId];
                if (commands) {
                    delete list._unknownRecordCommands[record.resId];
                    await applyCommands(list, commands);
                }
            }
        });
}

/**
 * @param {StaticList} list
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
