// @ts-check

/**
 * Characterisation tests for the x2many rollback shape used by
 * ``RelationalRecord._update`` (``rollbackLists``) and by ``_applyChanges``'s
 * undo closure. Both snapshot the SAME four fields — ``_commands``,
 * ``_currentIds``, ``count``, ``records`` — while ``applyCommands`` mutates
 * three more: ``_tmpIncreaseLimit`` / ``config.limit`` (via ``_bumpLimit``),
 * ``_unknownRecordCommands`` and ``_loadingStubIds``.
 *
 * ``StaticList._addSavePoint`` / ``_discard`` already snapshot the wider set,
 * so the three mechanisms disagree on what "the list's mutable state" is.
 * These tests pin the residue the narrow shape leaves behind.
 */

import { describe, expect, test } from "@odoo/hoot";
import { markRaw } from "@odoo/owl";
import { ListMembership } from "@web/model/relational_model/list_membership";
import { StaticList } from "@web/model/relational_model/static_list";

function makeList(overrides = {}) {
    const list = Object.create(StaticList.prototype);
    Object.assign(list, {
        // Membership owner first: the keys below write through its accessors.
        _membership: new ListMembership(),
        _config: {
            limit: 1,
            offset: 0,
            resIds: [1],
            orderBy: [],
            resModel: "res.partner",
            context: {},
            activeFields: {},
            fields: {},
        },
        records: [],
        count: 0,
        _cache: markRaw({}),
        _commands: [],
        _initialCommands: [],
        _commandsPromise: null,
        _savePoint: undefined,
        _unknownRecordCommands: {},
        _loadingStubIds: new Set(),
        _currentIds: [],
        _tmpIncreaseLimit: 0,
        _needsReordering: false,
        _extendedRecords: new Set(),
        _onUpdate: async () => {},
        model: {
            _patchConfig: (config, patch) => Object.assign(config, patch),
            _loadRecords: async () => [],
        },
        ...overrides,
    });
    return list;
}

/**
 * The snapshot/restore pair ``record._update`` (``rollbackLists``) and
 * ``record._applyChanges``'s undo closure both go through. Exercised via the
 * real ``StaticList`` primitives so this test tracks the production code
 * rather than a copy of it.
 */
function snapshotAsUpdateDoes(list) {
    return { list, snapshot: list._snapshot() };
}

function rollbackAsUpdateDoes(snap) {
    snap.list._restore(snap.snapshot);
}

describe("rollback completeness after a failed commit", () => {
    test("a SET wider than the page leaves limit/_tmpIncreaseLimit inflated", async () => {
        // ``preprocessX2manyChanges`` routes a SET command in a field change to
        // ``_replaceWith``, so this runs inside ``record._update``'s try block
        // and is covered by ``rollbackLists`` when the onchange then throws.
        const list = makeList({ _currentIds: [1], count: 1 });
        for (const id of [1, 2, 3]) {
            list._cache[id] = { resId: id, _virtualId: false };
        }
        list.records = [list._cache[1]];

        const snap = snapshotAsUpdateDoes(list);
        expect(list.limit).toBe(1);
        expect(list._tmpIncreaseLimit).toBe(0);

        await list._replaceWith([1, 2, 3]);
        expect(list.limit).toBe(3);
        expect(list._tmpIncreaseLimit).toBe(2);

        rollbackAsUpdateDoes(snap);

        expect(list._currentIds).toEqual([1]);
        expect(list.count).toBe(1);
        expect(list._commands).toEqual([]);
        // Residue: the page limit stays widened by the rolled-back SET.
        expect(list.limit).toBe(1);
        expect(list._tmpIncreaseLimit).toBe(0);
    });

    test("an UPDATE for an unloaded record leaves _unknownRecordCommands behind", async () => {
        const list = makeList({
            _config: {
                limit: 1,
                offset: 0,
                resIds: [1, 7],
                orderBy: [],
                resModel: "res.partner",
                context: {},
                activeFields: {},
                fields: {},
            },
            _currentIds: [1, 7],
            count: 2,
        });
        list._cache[1] = { resId: 1, _virtualId: false };
        list.records = [list._cache[1]];

        const snap = snapshotAsUpdateDoes(list);

        // Record 7 lives on an unloaded page: applyCommands stashes the payload.
        await list._applyCommands([[1, 7, { name: "from a change that will fail" }]]);
        expect(list._unknownRecordCommands[7]).toHaveLength(1);

        rollbackAsUpdateDoes(snap);

        expect(list._commands).toEqual([]);
        // Residue: the stash survives the rollback, so a later legitimate
        // [UPDATE, 7] re-attaches these values in serializeCommands.
        expect(list._unknownRecordCommands[7]).toBe(undefined);
    });
});

describe("_needsReordering is part of the restorable set", () => {
    test("a rollback across an add lowers the flag again", async () => {
        const list = makeList({
            _config: {
                limit: 5,
                offset: 0,
                resIds: [1],
                orderBy: [{ name: "sequence", asc: true }],
                resModel: "res.partner",
                context: {},
                activeFields: {},
                fields: {},
            },
            _currentIds: [1],
            count: 1,
        });
        list._cache[1] = { resId: 1, _virtualId: false, data: { sequence: 1 } };
        list.records = [list._cache[1]];
        expect(list._needsReordering).toBe(false);

        const snap = snapshotAsUpdateDoes(list);

        // What ``_addRecord`` does to the flag, without needing a datapoint
        // factory on this deliberately minimal mock: the point under test is
        // that the snapshot/restore pair covers the field at all.
        list._needsReordering = true;

        rollbackAsUpdateDoes(snap);

        // Left out of RESTORABLE_STATE this stayed true, and
        // ``computeNextOrderBy`` reads a raised flag as "reorder pending" and
        // returns the order unchanged — so the next header click did nothing.
        expect(list._needsReordering).toBe(false);
    });

    test("a flag raised BEFORE the snapshot survives the rollback", async () => {
        const list = makeList({ _needsReordering: true });
        const snap = snapshotAsUpdateDoes(list);
        list._needsReordering = false;
        rollbackAsUpdateDoes(snap);
        expect(list._needsReordering).toBe(true);
    });
});
