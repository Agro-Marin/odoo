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
import { getId, isX2Many } from "./field_context.js";

/** @import { StaticList } from "@web/model/relational_model/static_list" */

/**
 * Rewrite ``SET`` as the ``CLEAR`` + ``LINK`` sequence it means.
 *
 * ``[6, false, ids]`` says "the relation is exactly ``ids``", which is a reset
 * of membership followed by a link per id — precisely what the CLEAR and LINK
 * cases already implement. Expanding here keeps one implementation of each
 * effect instead of a third branch duplicating both.
 *
 * @param {[number, any, any][]} commands
 * @returns {[number, any, any][]}
 */
function expandSetCommands(commands) {
    const { LINK, SET, CLEAR } = x2ManyCommands;
    if (!commands.some((command) => command[0] === SET)) {
        return commands;
    }
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
    const { CREATE, UPDATE, DELETE, UNLINK, LINK, CLEAR } = x2ManyCommands;
    commands = expandSetCommands(commands);

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
    // Ids dropped by a CLEAR in THIS batch. A CLEAR only resets membership:
    // the commands after it re-declare the list, so an UPDATE/CREATE naming one
    // of these ids means "still a member, with these values" and must revive it
    // in place rather than be applied to a row that is about to be filtered out.
    const clearedIds = new Set();

    /**
     * Undo a CLEAR's removal for one id, keeping its current position.
     * @param {string | number} id
     * @returns {boolean} whether the id was cleared by this batch
     */
    function reviveClearedMember(id) {
        if (!clearedIds.has(id)) {
            return false;
        }
        clearedIds.delete(id);
        delete removedIds[id];
        currentIdsSet.add(id);
        return true;
    }

    for (const command of commands) {
        switch (command[0]) {
            case CLEAR: {
                // Membership only: the datapoints stay cached so the commands
                // that follow can revive them without a reload. Staged commands
                // described the list just discarded, so they go with it — the
                // CLEAR itself is staged in their place and serializes through
                // to the write (see serializeCommands).
                const hadContent =
                    list._currentIds.length > 0 ||
                    Object.keys(commandsByIds).length > 0;
                for (const id of list._currentIds) {
                    removedIds[id] = true;
                    clearedIds.add(id);
                    delete list._unknownRecordCommands[id];
                    list._loadingStubIds.delete(id);
                }
                currentIdsSet.clear();
                for (const key of Object.keys(commandsByIds)) {
                    delete commandsByIds[key];
                }
                if (hadContent) {
                    // Nothing to reset on an untouched empty list (a new record
                    // whose onchange answers with the conventional leading [5]);
                    // staging the command there would only prepend a no-op [5]
                    // to the create payload.
                    addOwnCommand([CLEAR, false, false]);
                }
                break;
            }
            case CREATE: {
                // An onchange echoes the client's own ``[0, virtualId, ...]``
                // back for a row the user may still be editing. Minting a fresh
                // id for it strands that datapoint — the open row loses its
                // input — and stages a second CREATE, so the save writes two
                // records where the user made one. Reuse the id we already own.
                const echoedId = command[1];
                const isEcho = Boolean(echoedId) && echoedId in list._cache;
                const virtualId = isEcho ? echoedId : getId("virtual");
                let record;
                if (isEcho) {
                    // Merge into the LIVE datapoint rather than rebuilding it:
                    // a freshly added row is not yet dirty, so
                    // ``_createRecordDatapoint`` would replace it with a
                    // readonly one and the row being edited would lose its
                    // input. Server slot, like the UPDATE case.
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
                    break; // already a member, at its current position
                }
                list.records.push(record);
                currentIdsSet.add(virtualId);
                const index = list.offset + list.limit;
                list._currentIds.splice(index, 0, virtualId);
                if (list.records.length > list.limit) {
                    list._bumpLimit(list.records.length - list.limit);
                }
                list.count++;
                break;
            }
            case UPDATE: {
                if (reviveClearedMember(command[1])) {
                    // ``[[5], [1, id, vals]]`` is the conventional "here is the
                    // whole list" answer: the UPDATE re-declares membership, so
                    // the staged commands need the link the CLEAR dropped.
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
                    // Record is on an unloaded page: mark it "unknown" and stash update
                    // commands to replay later if it's ever loaded.
                    if (!(command[1] in list._unknownRecordCommands)) {
                        list._unknownRecordCommands[command[1]] = [];
                    }
                    list._unknownRecordCommands[command[1]].push(command);
                } else if (
                    command[1] in list._unknownRecordCommands &&
                    list._loadingStubIds.has(command[1])
                ) {
                    // Record is cached but still loading (a page-fill stub, see
                    // the load below): keep stashing updates until it lands.
                    // The stub check matters: a LOADED record can also own a
                    // stash entry (deferred invisible-x2many slices, below) —
                    // stashing its later UPDATEs wholesale would leave the
                    // visible row stale until save.
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
                                !(fieldName in record.activeFields) // this record hasn't been extended
                            ) {
                                // Stash ONLY this field's slice: stashing the
                                // whole command permanently shadowed the
                                // record's own changeset at serialize time
                                // (see serializeCommands), silently dropping
                                // any later user edit to this row from the
                                // save payload.
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
                    // Server slot, not user slot: these UPDATE payloads are
                    // server-originated (onchange commands), and _applyChanges
                    // parses server values itself. Pre-parsing them into the
                    // USER slot corrupted _textValues provenance: a char/text
                    // the server set to false was stored as the parsed "", so
                    // a modifier like [("field", "=", False)] on the row
                    // mis-evaluated until reload (the server slot snapshots
                    // the RAW values via _getTextValues).
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
                    // ``absorbUnlinkIntoSet`` spliced this id out of the staged
                    // SET in ``list._commands`` in place, but ``list._commands``
                    // is rebuilt below from ``commandsByIds`` — a snapshot taken
                    // BEFORE the splice. Empty this id's bucket (keyed by the
                    // record id; the SET lives under ``false``) so its staged
                    // ``[UPDATE, id]`` is not resurrected — otherwise the save
                    // replaces the relation AND writes edits into a record the
                    // SET no longer contains.
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
                // An UNLINK absorbed into a staged SET only fixes the save
                // payload; membership must still be updated below — otherwise
                // the row keeps rendering, ``count`` drifts from the relation,
                // and validity scans keep visiting the ghost row.
                removedIds[command[1]] = true;
                // Prune any stashed deferred commands for this id: a record on
                // an unloaded page can accumulate UPDATE slices in
                // ``_unknownRecordCommands`` (see the UPDATE case). If it is
                // then removed, those stashes must go too — otherwise a later
                // page-fill that re-loads the same resId would replay stale
                // updates and resurrect values for a record the user deleted.
                delete list._unknownRecordCommands[command[1]];
                list._loadingStubIds.delete(command[1]);
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
                // Re-declares membership after a CLEAR by appending at the
                // payload's position; the pre-CLEAR copy is dropped by the
                // removedIds filter below. Drop it from ``clearedIds`` so a
                // later UPDATE for the same id does not ALSO revive the stale
                // copy in place — that would leave the row duplicated.
                clearedIds.delete(record.resId);
                const displayed =
                    !list.limit || list.records.length < list.limit || canAddOverLimit;
                if (displayed) {
                    if (!command[2]) {
                        recordsToLoad.push(record);
                    }
                    list.records.push(record);
                    if (list.records.length > list.limit) {
                        list._bumpLimit(list.records.length - list.limit);
                    }
                    // Membership must match the display: the row renders at
                    // the end of the CURRENT page, so insert its id there
                    // (mirrors CREATE above). A tail push would show the row
                    // here now but relocate it to the last page on the next
                    // load, and eval-context ``currentIds`` order would
                    // disagree with what the user sees.
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
                // Every command the x2many protocol defines has a case above
                // (SET is expanded into CLEAR + LINK on the way in), so this is
                // a malformed payload, not a gap — surface it loudly.
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
        // Rows removed from BEFORE the page start slide the whole membership
        // out from under the window. ``records`` still holds the right rows —
        // the filter below only drops the removed ones — but they now sit at a
        // lower index in ``_currentIds``, so the untouched ``offset`` stops
        // describing what is on screen: the pager counted one page while
        // another rendered, and the next ``_load`` teleported the user.
        // ``_clampOffset`` cannot catch this — the offset is still in range.
        // Shifting it back by the number of rows removed ahead of it keeps the
        // user on exactly the rows they were looking at.
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

    // Membership is settled: re-anchor the page window before filling it, so a
    // batch that emptied the current page renders the last page with data
    // instead of a blank one.
    list._clampOffset();

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
            list._loadingStubIds.add(id);
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
                        list._loadingStubIds.delete(record.resId);
                        continue;
                    }
                    record._applyValues(valuesById[record.resId]);
                    // Loaded: later UPDATEs must now apply live (only x2many
                    // slices may still be deferred, per the UPDATE case).
                    list._loadingStubIds.delete(record.resId);
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
