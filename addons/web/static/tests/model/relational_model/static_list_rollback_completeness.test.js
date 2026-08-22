// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { markRaw } from "@odoo/owl";
import { ListMembership } from "@web/model/relational_model/list_membership";
import { StaticList } from "@web/model/relational_model/static_list";

function makeList(overrides = {}) {
    const list = Object.create(StaticList.prototype);
    Object.assign(list, {
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
        _cache: markRaw(new Map()),
        _commands: [],
        _initialCommands: [],
        _commandsPromise: null,
        _savePoint: undefined,
        _unknownRecordCommands: new Map(),
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

function snapshotAsUpdateDoes(list) {
    return { list, snapshot: list._snapshot() };
}

function rollbackAsUpdateDoes(snap) {
    snap.list._restore(snap.snapshot);
}

describe("rollback completeness after a failed commit", () => {
    test("a SET wider than the page leaves limit/_tmpIncreaseLimit inflated", async () => {
        const list = makeList({ _currentIds: [1] });
        for (const id of [1, 2, 3]) {
            list._cache.set(id, { resId: id, _virtualId: false });
        }
        list.records = [list._cache.get(1)];

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
        });
        list._cache.set(1, { resId: 1, _virtualId: false });
        list.records = [list._cache.get(1)];

        const snap = snapshotAsUpdateDoes(list);

        await list._applyCommands([[1, 7, { name: "from a change that will fail" }]]);
        expect(list._unknownRecordCommands.get(7)).toHaveLength(1);

        rollbackAsUpdateDoes(snap);

        expect(list._commands).toEqual([]);
        expect(list._unknownRecordCommands.get(7)).toBe(undefined);
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
        });
        list._cache.set(1, { resId: 1, _virtualId: false, data: { sequence: 1 } });
        list.records = [list._cache.get(1)];
        expect(list._needsReordering).toBe(false);

        const snap = snapshotAsUpdateDoes(list);

        list._needsReordering = true;

        rollbackAsUpdateDoes(snap);

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
