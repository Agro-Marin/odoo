// @ts-check

/**
 * Pure unit tests for static_list_command_engine.js.
 *
 * Tests the applyCommands function which applies x2many ORM commands
 * (CREATE/UPDATE/DELETE/UNLINK/LINK) to a StaticList-shaped object.
 *
 * Uses a plain mock object — no OWL, no DOM, no mock server.
 * The function uses a delegation pattern and mutates its first argument,
 * so all assertions are on the mutated list state.
 */

import { describe, expect, test } from "@odoo/hoot";
import { applyCommands } from "@web/model/relational_model/static_list_command_engine";

// Command constants (matches x2ManyCommands in commands.js)
const CREATE = 0;
const UPDATE = 1;
const DELETE = 2;
const UNLINK = 3;
const LINK = 4;

// ---------------------------------------------------------------------------
// Mock factory
// ---------------------------------------------------------------------------

/**
 * Minimal StaticList mock with the exact shape applyCommands requires.
 *
 * @param {Object} [overrides]
 * @returns {Object}
 */
function makeList(overrides = {}) {
    let nextVirtualId = 1;

    const list = {
        _commands: [],
        records: [],
        _currentIds: [],
        _cache: {},
        _unknownRecordCommands: {},
        offset: 0,
        limit: 80,
        _tmpIncreaseLimit: 0,
        count: 0,
        config: {},
        fields: {},
        // Simulates _createRecordDatapoint: registers the record in _cache
        _createRecordDatapoint(data, opts = {}) {
            const virtualId = opts.virtualId || `virtual_${nextVirtualId++}`;
            const record = {
                resId: data.id || false,
                _virtualId: virtualId,
                activeFields: {},
                _applyChanges(changes) {
                    Object.assign(this.data, changes);
                },
                _applyValues(values) {
                    if (values) {
                        Object.assign(this.data, values);
                    }
                },
                _parseServerValues: (changes) => changes,
                data: { ...data },
            };
            if (data.id) {
                list._cache[data.id] = record;
            } else {
                list._cache[virtualId] = record;
            }
            return record;
        },
        _getResIdsToLoad: (ids) => ids,
        model: {
            _updateConfig: () => {},
            _loadRecords: () => Promise.resolve([]),
        },
        ...overrides,
    };
    return list;
}

/**
 * Add a real record to the list (as if already loaded from server).
 *
 * @param {Object} list
 * @param {number} resId
 * @returns {Object} the record
 */
function addRecord(list, resId) {
    const record = {
        resId,
        _virtualId: null,
        activeFields: {},
        data: { id: resId },
        _applyChanges(changes) { Object.assign(this.data, changes); },
        _applyValues(values) { if (values) Object.assign(this.data, values); },
        _parseServerValues: (changes) => changes,
    };
    list._cache[resId] = record;
    list.records.push(record);
    list._currentIds.push(resId);
    list.count++;
    return record;
}

// ---------------------------------------------------------------------------
// DELETE command
// ---------------------------------------------------------------------------

describe("applyCommands — DELETE", () => {
    test("removes record from records and _currentIds", () => {
        const list = makeList();
        addRecord(list, 1);
        addRecord(list, 2);

        applyCommands(list, [[DELETE, 1]]);

        expect(list.records.length).toBe(1);
        expect(list.records[0].resId).toBe(2);
        expect(list._currentIds).toEqual([2]);
    });

    test("updates count after DELETE", () => {
        const list = makeList();
        addRecord(list, 10);
        addRecord(list, 20);

        applyCommands(list, [[DELETE, 10]]);

        expect(list.count).toBe(1);
    });

    test("emits DELETE command in _commands", () => {
        const list = makeList();
        addRecord(list, 5);

        applyCommands(list, [[DELETE, 5]]);

        expect(list._commands.length).toBe(1);
        expect(list._commands[0][0]).toBe(DELETE);
        expect(list._commands[0][1]).toBe(5);
    });

    test("does NOT emit DELETE when record was just CREATE'd (cancels out)", () => {
        const list = makeList();
        // Pre-populate _commands with a CREATE for this virtual ID
        list._commands = [[CREATE, "virtual_1"]];
        list._currentIds = ["virtual_1"];
        const fakeRecord = { resId: false, _virtualId: "virtual_1" };
        list.records = [fakeRecord];
        list._cache["virtual_1"] = fakeRecord;
        list.count = 1;

        applyCommands(list, [[DELETE, "virtual_1"]]);

        // CREATE + DELETE cancel out — _commands should be empty
        expect(list._commands.length).toBe(0);
        expect(list.records.length).toBe(0);
    });

    test("handles DELETE of non-existent id gracefully", () => {
        const list = makeList();
        addRecord(list, 1);

        // DELETE id that is not in records/currentIds
        applyCommands(list, [[DELETE, 999]]);

        // Record 1 untouched
        expect(list.records.length).toBe(1);
        expect(list._currentIds).toEqual([1]);
    });

    test("multiple DELETE commands processed in order", () => {
        const list = makeList();
        addRecord(list, 1);
        addRecord(list, 2);
        addRecord(list, 3);

        applyCommands(list, [[DELETE, 1], [DELETE, 3]]);

        expect(list.records.length).toBe(1);
        expect(list.records[0].resId).toBe(2);
        expect(list._currentIds).toEqual([2]);
    });
});

// ---------------------------------------------------------------------------
// UNLINK command
// ---------------------------------------------------------------------------

describe("applyCommands — UNLINK", () => {
    test("removes record from records and _currentIds", () => {
        const list = makeList();
        addRecord(list, 7);
        addRecord(list, 8);

        applyCommands(list, [[UNLINK, 7]]);

        expect(list.records.length).toBe(1);
        expect(list.records[0].resId).toBe(8);
        expect(list._currentIds).toEqual([8]);
    });

    test("emits UNLINK command in _commands", () => {
        const list = makeList();
        addRecord(list, 3);

        applyCommands(list, [[UNLINK, 3]]);

        expect(list._commands.length).toBe(1);
        expect(list._commands[0][0]).toBe(UNLINK);
    });

    test("does NOT emit UNLINK when record was just LINK'd (cancels out)", () => {
        const list = makeList();
        // Pre-populate _commands with a LINK for id 3
        list._commands = [[LINK, 3]];
        addRecord(list, 3);

        applyCommands(list, [[UNLINK, 3]]);

        // LINK + UNLINK cancel out — no UNLINK emitted
        const unlinkCmds = list._commands.filter((c) => c[0] === UNLINK);
        expect(unlinkCmds.length).toBe(0);
    });
});

// ---------------------------------------------------------------------------
// LINK command
// ---------------------------------------------------------------------------

describe("applyCommands — LINK", () => {
    test("adds a cached record to records and _currentIds", () => {
        const list = makeList();
        const rec = { resId: 9, _virtualId: null, activeFields: {}, data: {} };
        list._cache[9] = rec;

        // Pass display data as command[2] so the record is not pushed to
        // recordsToLoad (which would require an async server fetch).
        applyCommands(list, [[LINK, 9, { id: 9, display_name: "Rec 9" }]]);

        expect(list.records.length).toBe(1);
        expect(list.records[0].resId).toBe(9);
        expect(list._currentIds).toInclude(9);
        expect(list.count).toBe(1);
    });

    test("creates a new record datapoint when id not in cache", () => {
        const list = makeList();

        applyCommands(list, [[LINK, 42, { name: "New Rec" }]]);

        expect(list.records.length).toBe(1);
        expect(list.records[0].resId).toBe(42);
        expect(list._currentIds).toInclude(42);
    });

    test("emits LINK command in _commands", () => {
        const list = makeList();

        applyCommands(list, [[LINK, 11]]);

        const linkCmds = list._commands.filter((c) => c[0] === LINK);
        expect(linkCmds.length).toBe(1);
        expect(linkCmds[0][1]).toBe(11);
    });

    test("is a no-op when record is already in _currentIds", () => {
        const list = makeList();
        addRecord(list, 5);
        const initialCount = list.count;

        // Try to LINK an already-present record
        applyCommands(list, [[LINK, 5]]);

        expect(list.count).toBe(initialCount);
        expect(list.records.length).toBe(1); // unchanged
    });

    test("re-links a previously deleted record (DELETE then LINK)", () => {
        const list = makeList();
        addRecord(list, 15);

        // DELETE 15 then LINK 15 in same batch
        applyCommands(list, [[DELETE, 15], [LINK, 15]]);

        // After DELETE, 15 is in removedIds; then LINK sees it's NOT in
        // _currentIds (was just removed), so it adds it back.
        expect(list._currentIds).toInclude(15);
    });
});

// ---------------------------------------------------------------------------
// UPDATE command
// ---------------------------------------------------------------------------

describe("applyCommands — UPDATE", () => {
    test("applies changes to a cached record", () => {
        const list = makeList();
        const record = addRecord(list, 20);
        list.fields = { name: { type: "char" } };
        record.activeFields = { name: {} };

        applyCommands(list, [[UPDATE, 20, { name: "Updated" }]]);

        expect(record.data.name).toBe("Updated");
    });

    test("stores command in _unknownRecordCommands when record not in cache", () => {
        // Override _getResIdsToLoad so the fill-page step doesn't trigger
        // a recursive applyCommands call (which would need full field defs).
        const list = makeList({ _getResIdsToLoad: () => [] });
        list._currentIds = [99]; // 99 is in the list but NOT in _cache

        applyCommands(list, [[UPDATE, 99, { name: "Ghost" }]]);

        expect(list._unknownRecordCommands[99]).toEqual([[UPDATE, 99, { name: "Ghost" }]]);
    });

    test("emits UPDATE command in _commands", () => {
        const list = makeList();
        addRecord(list, 30);
        list.fields = { name: { type: "char" } };

        applyCommands(list, [[UPDATE, 30, { name: "Changed" }]]);

        const updateCmds = list._commands.filter((c) => c[0] === UPDATE);
        expect(updateCmds.length).toBe(1);
    });

    test("deduplicates UPDATE: second UPDATE is redundant when first already emitted", () => {
        const list = makeList();
        addRecord(list, 40);
        list.fields = { name: { type: "char" } };

        // Two UPDATE commands for the same record in the same batch
        applyCommands(list, [
            [UPDATE, 40, { name: "First" }],
            [UPDATE, 40, { name: "Second" }],
        ]);

        // Only one UPDATE command emitted (second is redundant per isUpdateRedundant)
        const updateCmds = list._commands.filter((c) => c[0] === UPDATE);
        expect(updateCmds.length).toBe(1);
    });
});

// ---------------------------------------------------------------------------
// CREATE command
// ---------------------------------------------------------------------------

describe("applyCommands — CREATE", () => {
    test("adds a new virtual record to records and _currentIds", () => {
        const list = makeList();

        applyCommands(list, [[CREATE, false, { name: "New" }]]);

        expect(list.records.length).toBe(1);
        expect(list.records[0].resId).toBe(false); // virtual record has no server id
        expect(list.count).toBe(1);
        // _currentIds should contain the virtual ID
        expect(list._currentIds.length).toBe(1);
        expect(typeof list._currentIds[0]).toBe("string"); // virtual_N
    });

    test("emits CREATE command in _commands", () => {
        const list = makeList();

        applyCommands(list, [[CREATE, false, { name: "New" }]]);

        const createCmds = list._commands.filter((c) => c[0] === CREATE);
        expect(createCmds.length).toBe(1);
    });

    test("multiple CREATE commands produce multiple virtual records", () => {
        const list = makeList();

        applyCommands(list, [
            [CREATE, false, { name: "A" }],
            [CREATE, false, { name: "B" }],
        ]);

        expect(list.records.length).toBe(2);
        // Each has a unique virtual ID
        expect(list._currentIds[0]).not.toBe(list._currentIds[1]);
    });
});

// ---------------------------------------------------------------------------
// Command ordering and _commands rebuild
// ---------------------------------------------------------------------------

describe("applyCommands — command log integrity", () => {
    test("preserves existing _commands from prior operations", () => {
        const list = makeList();
        addRecord(list, 1);
        // Simulate a prior CREATE already in _commands
        list._commands = [[CREATE, "virtual_1"]];
        const fakeVirtual = {
            resId: false, _virtualId: "virtual_1",
            activeFields: {}, data: {},
            _applyChanges() {}, _parseServerValues: (v) => v,
        };
        list.records.push(fakeVirtual);
        list._currentIds.push("virtual_1");
        list._cache["virtual_1"] = fakeVirtual;
        list.count = 2;

        // Now DELETE the real record
        applyCommands(list, [[DELETE, 1]]);

        // _commands should have: CREATE for virtual_1 + DELETE for 1
        expect(list._commands.some((c) => c[0] === CREATE)).toBe(true);
        expect(list._commands.some((c) => c[0] === DELETE)).toBe(true);
    });

    test("command order is preserved by index", () => {
        const list = makeList();
        addRecord(list, 2);
        addRecord(list, 3);
        addRecord(list, 4);

        // Apply DELETE for records 2, 3, and 4 — should emit in same order
        applyCommands(list, [[DELETE, 2], [DELETE, 3], [DELETE, 4]]);

        const deletedIds = list._commands.map((c) => c[1]);
        expect(deletedIds).toEqual([2, 3, 4]);
    });
});
