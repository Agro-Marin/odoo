// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { x2ManyCommands } from "@web/core/network/commands";
import { StaticList } from "@web/model/relational_model/static_list";

const { SET, CLEAR, CREATE, UPDATE } = x2ManyCommands;

/**
 * @typedef {{
 * _virtualId: string | null,
 * resId: number | false,
 * data: Record<string, any>,
 * _applyChanges?: () => void,
 * }} FakeRow
 */

/**
 * @typedef {{
 * commands?: any[],
 * currentIds?: any[],
 * records?: FakeRow[],
 * limit?: number,
 * offset?: number,
 * }} EngineListParams
 */

function makeEngineList(
    /** @type {EngineListParams} */ {
        commands = [],
        currentIds = [],
        records = [],
        limit = 40,
        offset = 0,
    } = {},
) {
    /** @type {number[]} */
    const bumps = [];
    /** @type {Map<number | string, FakeRow>} */
    const cache = new Map();
    for (const rec of records) {
        cache.set(/** @type {number | string} */ (rec._virtualId || rec.resId), rec);
    }
    return {
        _commands: commands,
        _currentIds: currentIds,
        records,
        limit,
        offset,
        _cache: cache,
        /** @type {Set<any>} */
        _loadingStubIds: new Set(),
        _unknownRecordCommands: new Map(),
        _needsReordering: false,
        _bumps: bumps,
        _bumpLimit(/** @type {number} */ n) {
            bumps.push(n);
            this.limit += n;
        },
        _clampOffset() {},
        _commitCommands(/** @type {any[]} */ commands) {
            this._commands = commands;
        },
        _commitCurrentIds(/** @type {any[]} */ ids) {
            this._currentIds = ids;
        },
        _insertMemberAt(/** @type {number} */ index, /** @type {any} */ id) {
            this._currentIds.splice(index, 0, id);
        },
        _appendMember(/** @type {any} */ id) {
            this._currentIds.push(id);
        },
        _getResIdsToLoad: () => /** @type {any[]} */ ([]),
        _createRecordDatapoint(
            /** @type {Record<string, any>} */ values,
            /** @type {{ virtualId?: string }} */ opts = {},
        ) {
            /** @type {FakeRow} */
            const rec = {
                _virtualId: opts.virtualId ?? null,
                resId: false,
                data: values || {},
                _applyChanges() {},
            };
            if (opts.virtualId) {
                cache.set(opts.virtualId, rec);
            }
            return rec;
        },
        model: {
            _patchConfig() {},
            _loadRecords: async () => /** @type {any[]} */ ([]),
        },
        _applyCommands: StaticList.prototype._applyCommands,
    };
}

/**
 * @param {any} list
 * @param {string} virtualId
 * @param {Record<string, any>} [data]
 * @returns {FakeRow}
 */
function addVirtual(list, virtualId, data = {}) {
    /** @type {FakeRow} */
    const rec = { _virtualId: virtualId, resId: false, data, _applyChanges() {} };
    list._cache.set(virtualId, rec);
    return rec;
}

/**
 * @param {number} resId
 * @returns {FakeRow}
 */
function savedRow(resId) {
    return { _virtualId: null, resId, data: {}, _applyChanges() {} };
}

/**
 * @param {string} virtualId
 * @returns {FakeRow}
 */
function virtualRow(virtualId) {
    return { _virtualId: virtualId, resId: false, data: {}, _applyChanges() {} };
}

function makeSortableList() {
    /** @type {FakeRow} */
    const rec1 = { _virtualId: null, resId: 1, data: { name: "b" } };
    /** @type {FakeRow} */
    const rec2 = { _virtualId: null, resId: 2, data: { name: "c" } };
    /** @type {FakeRow} */
    const recV = { resId: false, _virtualId: "v", data: { name: "a" } };
    return {
        records: [rec1, rec2],
        _cache: new Map(
            /** @type {[number | string, FakeRow][]} */ ([
                [1, rec1],
                [2, rec2],
                ["v", recV],
            ]),
        ),
        /** @type {any[]} */
        _currentIds: [1, 2],
        /** @type {any[]} */
        _commands: [],
        limit: 40,
        offset: 0,
        count: 2,
        orderBy: [{ name: "name", asc: true }],
        fields: { name: { type: "char" } },
        model: { _patchConfig() {} },
        config: {},
        _getResIdsToLoad: () => /** @type {any[]} */ ([]),
        _load: StaticList.prototype._load,
        markReordered() {
            /** @type {any} */ (this)._needsReordering = false;
        },
    };
}

describe("StaticList._addRecord(top) command ordering", () => {
    test("inserts CREATE AFTER a leading SET so the new row survives", async () => {
        const list = makeEngineList({ commands: [[SET, false, [1, 2]]] });
        const rec = addVirtual(list, "virt-1");

        await StaticList.prototype._addRecord.call(list, /** @type {any} */ (rec), {
            position: "top",
        });

        expect(list._commands).toEqual([
            [SET, false, [1, 2]],
            [CREATE, "virt-1"],
        ]);
        expect(list.records[0]).toBe(rec);
    });

    test("with no SET/CLEAR, CREATE goes to the front (before other commands)", async () => {
        const list = makeEngineList({ commands: [[UPDATE, 5, {}]] });
        const rec = addVirtual(list, "virt-2");

        await StaticList.prototype._addRecord.call(list, /** @type {any} */ (rec), {
            position: "top",
        });

        expect(list._commands).toEqual([
            [CREATE, "virt-2"],
            [UPDATE, 5, {}],
        ]);
    });

    test("default add on a sorted list keeps _currentIds in the sorted order", async () => {
        const list = makeSortableList();
        const recV = /** @type {any} */ (list._cache).get("v");

        await StaticList.prototype._addRecord.call(list, /** @type {any} */ (recV));

        expect(list._currentIds).toEqual(["v", 1, 2]);
        expect(list.records.map((r) => r.data.name)).toEqual(["a", "b", "c"]);
        expect(list._commands).toEqual([[CREATE, "v"]]);
    });

    test("inserts after BOTH a leading CLEAR and SET", async () => {
        const list = makeEngineList({
            commands: [
                [CLEAR, false, false],
                [SET, false, [1, 2]],
            ],
        });
        const rec = addVirtual(list, "virt-3");

        await StaticList.prototype._addRecord.call(list, /** @type {any} */ (rec), {
            position: "top",
        });

        expect(list._commands[2]).toEqual([CREATE, "virt-3"]);
    });
});

describe("StaticList._addRecord insertion-rule characterization", () => {
    test("bottom add appends the row, id at offset+limit, and the CREATE command", async () => {
        const list = makeEngineList({
            records: [savedRow(1), savedRow(2)],
            currentIds: [1, 2],
            limit: 40,
        });
        const recB = addVirtual(list, "vb");

        await StaticList.prototype._addRecord.call(list, /** @type {any} */ (recB), {
            position: "bottom",
        });

        expect(list._currentIds).toEqual([1, 2, "vb"]);
        expect(list.records.map((r) => r._virtualId ?? r.resId)).toEqual([1, 2, "vb"]);
        expect(list._commands).toEqual([[CREATE, "vb"]]);
        expect(list._bumps).toEqual([]);
        expect(list._needsReordering).toBe(true);
    });

    test("bottom add over a full page bumps the limit by one to keep the row", async () => {
        const list = makeEngineList({
            records: [virtualRow("a"), virtualRow("b")],
            currentIds: ["a", "b"],
            limit: 2,
        });
        const recC = addVirtual(list, "c");

        await StaticList.prototype._addRecord.call(list, /** @type {any} */ (recC), {
            position: "bottom",
        });

        expect(list.records.map((r) => r._virtualId)).toEqual(["a", "b", "c"]);
        expect(list._currentIds).toEqual(["a", "b", "c"]);
        expect(list._bumps).toEqual([1]);
    });

    test("top add on a full page pops the last row to hold the window", async () => {
        const list = makeEngineList({
            records: [virtualRow("a"), virtualRow("b")],
            currentIds: ["a", "b"],
            limit: 2,
        });
        const recC = addVirtual(list, "c");

        await StaticList.prototype._addRecord.call(list, /** @type {any} */ (recC), {
            position: "top",
        });

        expect(list.records.map((r) => r._virtualId)).toEqual(["c", "a"]);
        expect(list._currentIds).toEqual(["c", "a", "b"]);
        expect(list._commands).toEqual([[CREATE, "c"]]);
    });

    test("default add with sort:false appends without reordering", async () => {
        const list = {
            records: [{ _virtualId: "a" }],
            _currentIds: ["a"],
            /** @type {any[]} */
            _commands: [],
            limit: 40,
            offset: 0,
            /** @type {any[]} */
            orderBy: [],
        };

        await StaticList.prototype._addRecord.call(
            list,
            /** @type {any} */ ({ _virtualId: "b" }),
            { sort: false },
        );

        expect(list._currentIds).toEqual(["a", "b"]);
        expect(list.records.map((r) => r._virtualId)).toEqual(["a", "b"]);
        expect(list._commands).toEqual([[CREATE, "b"]]);
    });
});
