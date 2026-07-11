// @ts-check

/**
 * State-integrity tests for StaticList internals:
 *  - ``_pruneCache`` pins ids referenced by a live ``_savePoint`` (a later
 *    ``_discard`` maps them through ``_cache``) and drops ``_extendedRecords``
 *    entries only for evicted records (wholesale clearing forced the next
 *    dialog open through extendRecord's first-extension path again).
 *  - ``_abandonRecords`` must not splice with a -1 index when the abandoned
 *    record's virtualId is not in ``_currentIds`` (splice(-1, 1) removes the
 *    LAST id).
 *  - ``_addNewRecordAtIndex`` must survive an out-of-range index (account's
 *    section widget passes -1 for a first section) instead of crashing on
 *    ``records[-1].id``.
 *
 * Uses ``Object.create(StaticList.prototype)`` against hand-built state,
 * mirroring static_list_pending_commands.test.js.
 */

import { describe, expect, test } from "@odoo/hoot";
import { markRaw } from "@odoo/owl";
import { StaticList } from "@web/model/relational_model/static_list";

function makeList(overrides = {}) {
    const list = Object.create(StaticList.prototype);
    Object.assign(list, {
        _config: {
            limit: 40,
            offset: 0,
            resIds: [],
            orderBy: [],
            resModel: "res.partner",
            context: {},
            activeFields: {},
            fields: { sequence: { type: "integer" } },
        },
        records: [],
        count: 0,
        _cache: markRaw({}),
        _commands: [],
        _initialCommands: [],
        _commandsPromise: null,
        _savePoint: undefined,
        _unknownRecordCommands: {},
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

describe("_pruneCache", () => {
    test("evicts ids absent from _currentIds, keeps live ones", () => {
        const list = makeList({ _currentIds: [1] });
        list._cache[1] = { id: "dp1" };
        list._cache[2] = { id: "dp2" };

        list._pruneCache();

        expect(1 in list._cache).toBe(true);
        expect(2 in list._cache).toBe(false);
    });

    test("ids referenced by a live _savePoint are pinned", () => {
        const list = makeList({ _currentIds: [1] });
        list._cache[1] = { id: "dp1" };
        list._cache[2] = { id: "dp2" };
        list._cache[3] = { id: "dp3" };
        // A dialog savepoint (extendRecord) still references id 2: a later
        // _discard rebuilds records by mapping it through _cache.
        list._savePoint = markRaw({
            _commands: [],
            _currentIds: [1, 2],
            count: 2,
        });

        list._pruneCache();

        expect(1 in list._cache).toBe(true);
        expect(2 in list._cache).toBe(true);
        expect(3 in list._cache).toBe(false);
    });

    test("_extendedRecords only loses entries for evicted records", () => {
        const list = makeList({ _currentIds: [1] });
        list._cache[1] = { id: "dp1" };
        list._cache[2] = { id: "dp2" };
        list._extendedRecords.add("dp1");
        list._extendedRecords.add("dp2");

        list._pruneCache();

        // dp1 is still cached: its extension state must survive, or the next
        // dialog open re-runs the first-extension load.
        expect(list._extendedRecords.has("dp1")).toBe(true);
        expect(list._extendedRecords.has("dp2")).toBe(false);
    });
});

describe("_abandonRecords", () => {
    function makeAbandonable(virtualId) {
        return {
            id: `dp_${virtualId}`,
            resId: false,
            _virtualId: virtualId,
            canBeAbandoned: true,
            _checkValidity: () => true,
        };
    }

    test("removes an abandoned record present in the list", () => {
        const list = makeList();
        const rec = makeAbandonable("virtual_1");
        list.records = [rec];
        list._currentIds = ["virtual_1", 7];
        list._commands = [[0, "virtual_1"]];
        list.count = 2;

        list._abandonRecords([rec], { force: true });

        expect(list._currentIds).toEqual([7]);
        expect(list.records).toEqual([]);
        expect(list._commands).toEqual([]);
        expect(list.count).toBe(1);
    });

    test("a record absent from _currentIds is skipped, not spliced at -1", () => {
        const list = makeList();
        // e.g. a dialog-created record not yet validated into the list
        const rec = makeAbandonable("virtual_ghost");
        list.records = [];
        list._currentIds = [7, 8];
        list.count = 2;

        list._abandonRecords([rec], { force: true });

        // splice(-1, 1) would have removed the LAST id (8).
        expect(list._currentIds).toEqual([7, 8]);
        expect(list.count).toBe(2);
    });
});

describe("_addNewRecordAtIndex", () => {
    function makeSequencedList() {
        const cache = markRaw({});
        const makeRec = (resId, sequence) => {
            const rec = {
                id: `dp_${resId}`,
                resId,
                _virtualId: null,
                dirty: false,
                data: { sequence },
                _loadedFieldNames: new Set(["sequence"]),
                _update(changes) {
                    Object.assign(this.data, changes);
                    this.dirty = true;
                    return Promise.resolve();
                },
            };
            cache[resId] = rec;
            return rec;
        };
        const r1 = makeRec(1, 1);
        const r2 = makeRec(2, 2);
        const list = makeList({
            _config: {
                limit: 40,
                offset: 0,
                resIds: [1, 2],
                orderBy: [{ name: "sequence", asc: true }],
                resModel: "res.partner",
                context: {},
                activeFields: {},
                fields: { sequence: { type: "integer" } },
            },
            handleField: "sequence",
            records: [r1, r2],
            _currentIds: [1, 2],
            _cache: cache,
            count: 2,
        });
        list._createNewRecordDatapoint = async () => {
            const rec = {
                id: "dp_new",
                resId: false,
                _virtualId: "virtual_new",
                dirty: true,
                data: { sequence: 0 },
                _loadedFieldNames: new Set(["sequence"]),
                _update(changes) {
                    Object.assign(this.data, changes);
                    return Promise.resolve();
                },
            };
            cache["virtual_new"] = rec;
            return rec;
        };
        return list;
    }

    test("index -1 (first section) resequences to the top without crashing", async () => {
        const list = makeSequencedList();

        const newRecord = await list._addNewRecordAtIndex(-1);

        expect(newRecord.id).toBe("dp_new");
        // The untouched new row is force-clean (its handle change still ships
        // with the parent's CREATE command).
        expect(newRecord.dirty).toBe(false);
        expect(list.records[0]).toBe(newRecord);
        expect(list.count).toBe(3);
    });

    test("an overflow index clamps to the last record", async () => {
        const list = makeSequencedList();

        const newRecord = await list._addNewRecordAtIndex(99);

        expect(newRecord.dirty).toBe(false);
        expect(list.records.at(-1)).toBe(newRecord);
        expect(list.count).toBe(3);
    });
});
