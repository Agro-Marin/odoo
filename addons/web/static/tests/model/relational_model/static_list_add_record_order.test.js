// @ts-check

/**
 * Characterization of StaticList._addRecord's interactive insertion rules.
 *
 * As of the F-U05-9 unification, `_addRecord`'s top/bottom branches no longer
 * interpret the CREATE command themselves -- they delegate to the extracted
 * engine (`applyCommands` -> `applyCreate`), which is now position-aware. These
 * tests therefore drive the *real* `_addRecord` on top of a list fake rich
 * enough to run the engine end to end (echoed datapoint in `_cache`, a working
 * `_bumpLimit`, no-op page-refill helpers), and pin the observables the
 * unification must not move: the `_commands` order, the `_currentIds` order, the
 * `records` window, when the limit bumps, and the `_needsReordering` flag.
 *
 * The load-bearing command-order rule: a top add's CREATE must land AFTER any
 * leading SET/CLEAR (from `_replaceWith`) but BEFORE every other command. The
 * server applies commands in order, so a CREATE placed before a SET is created
 * and then wiped when the SET replaces the whole relation; and for a non-
 * sequenced one2many the create order becomes the server id order, so the
 * visually-topmost new row must be created first. The engine reproduces this via
 * `topInsertIndex` (a fractional ordering index at the SET/CLEAR-prefix
 * boundary); these tests are its oracle.
 */

import { describe, expect, test } from "@odoo/hoot";
import { x2ManyCommands } from "@web/core/network/commands";
import { StaticList } from "@web/model/relational_model/static_list";

const { SET, CLEAR, CREATE, UPDATE } = x2ManyCommands;

/**
 * A datapoint stand-in. The engine only ever reads these four members off a
 * row, so the fakes below carry exactly them -- naming the shape once keeps
 * every builder agreeing on it instead of each re-inferring its own literal.
 *
 * @typedef {{
 *   _virtualId: string | null,
 *   resId: number | false,
 *   data: Record<string, any>,
 *   _applyChanges?: () => void,
 * }} FakeRow
 */

/**
 * @typedef {{
 *   commands?: any[],
 *   currentIds?: any[],
 *   records?: FakeRow[],
 *   limit?: number,
 *   offset?: number,
 * }} EngineListParams
 */

/**
 * A list fake that faithfully supports the command engine: it carries the real
 * `_applyCommands`, an echo cache seeded from `records`, a limit-bumping
 * `_bumpLimit`, and page-refill helpers stubbed to no-ops so the window
 * assertions stay about the insertion, not about server reloads.
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
    /** @type {Record<string, FakeRow>} */
    const cache = {};
    for (const rec of records) {
        cache[String(rec._virtualId ?? rec.resId)] = rec;
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
        _unknownRecordCommands: {},
        _needsReordering: false,
        _bumps: bumps,
        _bumpLimit(/** @type {number} */ n) {
            bumps.push(n);
            this.limit += n;
        },
        _clampOffset() {},
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
                cache[opts.virtualId] = rec;
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
 * Build a virtual (unsaved) datapoint and cache it so the engine echoes it.
 *
 * @param {any} list
 * @param {string} virtualId
 * @param {Record<string, any>} [data]
 * @returns {FakeRow}
 */
function addVirtual(list, virtualId, data = {}) {
    /** @type {FakeRow} */
    const rec = { _virtualId: virtualId, resId: false, data, _applyChanges() {} };
    list._cache[virtualId] = rec;
    return rec;
}

/**
 * Build a saved-row datapoint (has a resId, no virtualId).
 *
 * @param {number} resId
 * @returns {FakeRow}
 */
function savedRow(resId) {
    return { _virtualId: null, resId, data: {}, _applyChanges() {} };
}

/**
 * Build an unsaved-row datapoint already parked in the window.
 *
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
        /** @type {Record<string, FakeRow>} */
        _cache: { 1: rec1, 2: rec2, v: recV },
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
        // The sort helper clears the pending-reorder flag through this method
        // (published in the StaticList reorder-flag encapsulation); the hand-
        // built list must provide it just like `_load` above.
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
        const recV = list._cache.v;

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
        expect(list._bumps).toEqual([]); // still under the limit -- no bump
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

        // unshift then pop past the limit: the window stays at 2, ids keep all 3.
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
