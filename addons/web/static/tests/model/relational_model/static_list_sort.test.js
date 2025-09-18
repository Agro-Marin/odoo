// @ts-check

/**
 * Pure unit tests for static_list_sort.js.
 *
 * Tests sort() early-exit path and sortBy() direction cycling.
 * The full sort path (with server record loading and list._load) requires
 * integration-level infrastructure and is covered by the existing
 * x2many/list view integration tests.
 */

import { describe, expect, test } from "@odoo/hoot";
import { sort, sortBy } from "@web/model/relational_model/static_list_sort";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Minimal StaticList mock for sort/sortBy tests.
 * Captures calls to _load so we can assert the arguments.
 */
function makeList(overrides = {}) {
    const loadCalls = [];
    const list = {
        currentIds: [],
        _currentIds: [],
        orderBy: [],
        _needsReordering: false,
        activeFields: {},
        fields: {},
        config: {},
        _cache: {},
        _getResIdsToLoad: () => [], // no server loading needed
        _load: async (params) => {
            loadCalls.push(params);
        },
        _createRecordDatapoint: () => {},
        model: {
            _loadRecords: async () => [],
        },
        _loadCalls: loadCalls,
        ...overrides,
    };
    return list;
}

// ---------------------------------------------------------------------------
// sort — empty orderBy (early return)
// ---------------------------------------------------------------------------

describe("sort — empty orderBy", () => {
    test("returns currentIds unchanged when orderBy is empty", async () => {
        const list = makeList();
        const ids = [3, 1, 2];
        const result = await sort(list, ids, []);
        expect(result).toBe(ids);
    });

    test("does not call list._load when orderBy is empty", async () => {
        const list = makeList();
        await sort(list, [1, 2], []);
        expect(list._loadCalls.length).toBe(0);
    });

    test("uses list.orderBy default when not provided", async () => {
        const list = makeList({ orderBy: [] });
        const ids = [5, 6];
        const result = await sort(list, ids);
        // Empty orderBy → early return with same array
        expect(result).toBe(ids);
    });
});

// ---------------------------------------------------------------------------
// sort — non-empty orderBy with all records in cache
// ---------------------------------------------------------------------------

describe("sort — with cached records", () => {
    test("sorts records by field and calls _load with sorted IDs", async () => {
        const list = makeList({
            fields: { name: { type: "char" } },
        });
        // Pre-populate cache with records
        list._cache = {
            1: { resId: 1, _virtualId: null, data: { name: "Zebra" } },
            2: { resId: 2, _virtualId: null, data: { name: "Apple" } },
            3: { resId: 3, _virtualId: null, data: { name: "Mango" } },
        };

        await sort(list, [1, 2, 3], [{ name: "name", asc: true }]);

        // _load should be called with IDs in sorted order: Apple(2), Mango(3), Zebra(1)
        expect(list._loadCalls.length).toBe(1);
        expect(list._loadCalls[0].nextCurrentIds).toEqual([2, 3, 1]);
    });

    test("clears _needsReordering flag after sort", async () => {
        const list = makeList({
            fields: { name: { type: "char" } },
            _needsReordering: true,
        });
        list._cache = {
            1: { resId: 1, data: { name: "A" } },
        };

        await sort(list, [1], [{ name: "name", asc: true }]);

        expect(list._needsReordering).toBe(false);
    });

    test("descending sort reverses the order", async () => {
        const list = makeList({
            fields: { name: { type: "char" } },
        });
        list._cache = {
            1: { resId: 1, data: { name: "Apple" } },
            2: { resId: 2, data: { name: "Zebra" } },
        };

        await sort(list, [1, 2], [{ name: "name", asc: false }]);

        expect(list._loadCalls[0].nextCurrentIds).toEqual([2, 1]);
    });
});

// ---------------------------------------------------------------------------
// sortBy — direction cycling
// ---------------------------------------------------------------------------

describe("sortBy — direction cycling", () => {
    test("new field sorts ascending", async () => {
        const list = makeList({
            orderBy: [],
            fields: { name: { type: "char" } },
            _cache: {
                1: { resId: 1, data: { name: "A" } },
            },
        });

        await sortBy(list, "name");

        // _load should be called with orderBy: [{name: "name", asc: true}]
        expect(list._loadCalls.length).toBe(1);
        expect(list._loadCalls[0].orderBy).toEqual([{ name: "name", asc: true }]);
    });

    test("same field asc → sorts descending", async () => {
        const list = makeList({
            orderBy: [{ name: "name", asc: true }],
            _needsReordering: false,
            fields: { name: { type: "char" } },
            _cache: {
                1: { resId: 1, data: { name: "A" } },
            },
        });

        await sortBy(list, "name");

        expect(list._loadCalls[0].orderBy).toEqual([{ name: "name", asc: false }]);
    });

    test("same field desc → resets to id asc", async () => {
        const list = makeList({
            orderBy: [{ name: "name", asc: false }],
            _needsReordering: false,
            fields: { id: { type: "integer" } },
            _cache: {
                1: { resId: 1, data: {} },
            },
        });

        await sortBy(list, "name");

        // After desc → reset to id asc (early return, no sort needed)
        // sort([{name:"id",asc:true}]) with empty cache would just early-exit if orderBy not empty
        // Actually it would try to sort by id. Let me check _currentIds — it's empty.
        // With currentIds=[] and orderBy=[{name:"id",asc:true}], allRecords=[]
        // sorted=[], _load({orderBy, nextCurrentIds:[]})
        expect(list._loadCalls.length).toBe(1);
        expect(list._loadCalls[0].orderBy).toEqual([{ name: "id", asc: true }]);
    });
});
