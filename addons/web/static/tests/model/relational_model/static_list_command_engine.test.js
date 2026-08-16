// @ts-check

/**
 * Unit tests for applyCommands (static_list_command_engine.js): applies x2many
 * ORM commands (CREATE/UPDATE/DELETE/UNLINK/LINK) to a StaticList-shaped mock —
 * no OWL/DOM/mock server. It mutates its first argument, so assertions read
 * the mutated list state.
 */

import { describe, expect, test } from "@odoo/hoot";
import { applyCommands } from "@web/model/relational_model/static_list_command_engine";

describe.current.tags("headless");

const CREATE = 0;
const UPDATE = 1;
const DELETE = 2;
const UNLINK = 3;
const LINK = 4;
const CLEAR = 5;

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
        _loadingStubIds: new Set(),
        offset: 0,
        limit: 80,
        _tmpIncreaseLimit: 0,
        // Derived, exactly as the real StaticList derives it. A fixture that
        // can hold `count` out of step with `_currentIds` can be set up in a
        // state the production code cannot reach, and then the assertions are
        // about that impossible state rather than about the engine.
        get count() {
            return this._currentIds.length;
        },
        config: {},
        fields: {},
        _createRecordDatapoint(/** @type {any} */ data, opts = {}) {
            const virtualId = opts.virtualId || `virtual_${nextVirtualId++}`;
            const record = {
                resId: data.id || false,
                _virtualId: virtualId,
                activeFields: {},
                _applyChanges(/** @type {any} */ changes, serverChanges = {}) {
                    Object.assign(
                        this.data,
                        changes,
                        this._parseServerValues(serverChanges),
                    );
                },
                _applyValues(/** @type {any} */ values) {
                    if (values) {
                        Object.assign(this.data, values);
                    }
                },
                _parseServerValues: (/** @type {any} */ changes) => changes,
                data: { ...data },
            };
            if (data.id) {
                list._cache[data.id] = record;
            } else {
                list._cache[virtualId] = record;
            }
            return record;
        },
        _getResIdsToLoad: (/** @type {any} */ ids) => ids,
        _bumpLimit(/** @type {any} */ n) {
            this._tmpIncreaseLimit += n;
            this.model._patchConfig(this.config, { limit: this.limit + n });
        },
        _clampOffset() {
            const length = this._currentIds.length;
            if (this.offset === 0 || this.offset < length) {
                return;
            }
            this.offset =
                length && this.limit > 0
                    ? Math.floor((length - 1) / this.limit) * this.limit
                    : 0;
        },
        model: {
            _patchConfig: () => {},
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
        _applyChanges(/** @type {any} */ changes, serverChanges = {}) {
            Object.assign(this.data, changes, this._parseServerValues(serverChanges));
        },
        _applyValues(/** @type {any} */ values) {
            if (values) {
                Object.assign(this.data, values);
            }
        },
        _parseServerValues: (/** @type {any} */ changes) => changes,
    };
    list._cache[resId] = record;
    list.records.push(record);
    list._currentIds.push(resId);
    return record;
}

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
        list._commands = [[CREATE, "virtual_1"]];
        list._currentIds = ["virtual_1"];
        const fakeRecord = { resId: false, _virtualId: "virtual_1" };
        list.records = [fakeRecord];
        list._cache["virtual_1"] = fakeRecord;

        applyCommands(list, [[DELETE, "virtual_1"]]);

        expect(list._commands.length).toBe(0);
        expect(list.records.length).toBe(0);
    });

    test("handles DELETE of non-existent id gracefully", () => {
        const list = makeList();
        addRecord(list, 1);

        applyCommands(list, [[DELETE, 999]]);

        expect(list.records.length).toBe(1);
        expect(list._currentIds).toEqual([1]);
    });

    test("multiple DELETE commands processed in order", () => {
        const list = makeList();
        addRecord(list, 1);
        addRecord(list, 2);
        addRecord(list, 3);

        applyCommands(list, [
            [DELETE, 1],
            [DELETE, 3],
        ]);

        expect(list.records.length).toBe(1);
        expect(list.records[0].resId).toBe(2);
        expect(list._currentIds).toEqual([2]);
    });
});

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
        list._commands = [[LINK, 3]];
        addRecord(list, 3);

        applyCommands(list, [[UNLINK, 3]]);

        const unlinkCmds = list._commands.filter(
            (/** @type {any} */ c) => c[0] === UNLINK,
        );
        expect(unlinkCmds.length).toBe(0);
    });

    test("an UNLINK absorbed into a staged SET still drops membership", () => {
        const SET = 6;
        const list = makeList();
        list._commands = [[SET, false, [1, 2, 3]]];
        addRecord(list, 1);
        addRecord(list, 2);
        addRecord(list, 3);
        expect(list.count).toBe(3);

        applyCommands(list, [[UNLINK, 2]]);

        expect(list._commands[0]).toEqual([SET, false, [1, 3]]);
        expect(list._currentIds).toEqual([1, 3]);
        expect(list.records.map((/** @type {any} */ r) => r.resId)).toEqual([1, 3]);
        expect(list.count).toBe(2);
    });

    test("an UNLINK absorbed into a staged SET also drops that row's staged UPDATE", () => {
        // The observable half of absorbUnlinkIntoSet: once the row is gone from
        // the SET payload, an UPDATE still naming it would be sent for a row
        // this batch never links.
        const SET = 6;
        const list = makeList();
        list._commands = [[SET, false, [1, 2, 3]]];
        addRecord(list, 1);
        addRecord(list, 2);
        addRecord(list, 3);

        applyCommands(list, [[UPDATE, 2, { name: "edited" }]]);
        expect(
            list._commands.some(
                (/** @type {any} */ c) => c[0] === UPDATE && c[1] === 2,
            ),
        ).toBe(true);

        applyCommands(list, [[UNLINK, 2]]);

        expect(list._commands).toEqual([[SET, false, [1, 3]]]);
    });
});

describe("applyCommands — LINK", () => {
    test("adds a cached record to records and _currentIds", () => {
        const list = makeList();
        const rec = { resId: 9, _virtualId: null, activeFields: {}, data: {} };
        list._cache[9] = rec;

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

        const linkCmds = list._commands.filter((/** @type {any} */ c) => c[0] === LINK);
        expect(linkCmds.length).toBe(1);
        expect(linkCmds[0][1]).toBe(11);
    });

    test("is a no-op when record is already in _currentIds", () => {
        const list = makeList();
        addRecord(list, 5);
        const initialCount = list.count;

        applyCommands(list, [[LINK, 5]]);

        expect(list.count).toBe(initialCount);
        expect(list.records.length).toBe(1);
    });

    test("re-links a previously deleted record (DELETE then LINK)", () => {
        const list = makeList();
        addRecord(list, 15);

        applyCommands(list, [
            [DELETE, 15],
            [LINK, 15],
        ]);

        expect(list._currentIds).toInclude(15);
    });

    test("a displayed LINK is inserted at its page position, not the tail", () => {
        const list = makeList();
        list.limit = 3;
        list.offset = 0;
        addRecord(list, 1);
        addRecord(list, 2);
        list._currentIds = [1, 2, 90, 91];

        applyCommands(list, [[LINK, 9, { id: 9, display_name: "Rec 9" }]]);

        expect(list._currentIds).toEqual([1, 2, 9, 90, 91]);
        expect(list.records.map((/** @type {any} */ r) => r.resId)).toEqual([1, 2, 9]);
    });

    test("a LINK past the page limit appends to membership (not displayed)", () => {
        const list = makeList();
        list.limit = 2;
        list.offset = 0;
        addRecord(list, 1);
        addRecord(list, 2);
        list._currentIds = [1, 2];

        applyCommands(list, [[LINK, 9]]);

        expect(list._currentIds).toEqual([1, 2, 9]);
        expect(list.records.map((/** @type {any} */ r) => r.resId)).toEqual([1, 2]);
    });
});

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
        const list = makeList({ _getResIdsToLoad: () => [] });
        list._currentIds = [99];

        applyCommands(list, [[UPDATE, 99, { name: "Ghost" }]]);

        expect(list._unknownRecordCommands[99]).toEqual([
            [UPDATE, 99, { name: "Ghost" }],
        ]);
    });

    test("stashes only the invisible sub-x2many slice, applies the rest", () => {
        const list = makeList();
        const record = addRecord(list, 20);
        list.fields = {
            name: { type: "char" },
            lines: { type: "one2many" },
        };
        record.activeFields = {
            name: {},
        };

        applyCommands(list, [[UPDATE, 20, { name: "Updated", lines: [[5, 0, 0]] }]]);

        expect(record.data.name).toBe("Updated");
        expect(list._unknownRecordCommands[20]).toEqual([
            [UPDATE, 20, { lines: [[5, 0, 0]] }],
        ]);
    });

    test("a later UPDATE to a LOADED record with a deferred slice applies live", () => {
        const list = makeList();
        const record = addRecord(list, 20);
        list.fields = {
            name: { type: "char" },
            lines: { type: "one2many" },
        };
        record.activeFields = { name: {} };

        applyCommands(list, [[UPDATE, 20, { name: "First", lines: [[5, 0, 0]] }]]);
        expect(record.data.name).toBe("First");
        expect(list._unknownRecordCommands[20]).toEqual([
            [UPDATE, 20, { lines: [[5, 0, 0]] }],
        ]);
        expect(list._loadingStubIds.has(20)).toBe(false);

        applyCommands(list, [[UPDATE, 20, { name: "Second" }]]);
        expect(record.data.name).toBe("Second");
        expect(list._unknownRecordCommands[20]).toEqual([
            [UPDATE, 20, { lines: [[5, 0, 0]] }],
        ]);
    });

    test("routes UPDATE payloads through the SERVER slot of _applyChanges, unparsed", () => {
        const list = makeList();
        const record = addRecord(list, 20);
        list.fields = { name: { type: "char" } };
        record.activeFields = { name: {} };
        const calls = [];
        record._applyChanges = (/** @type {any} */ changes, serverChanges = {}) => {
            calls.push([changes, serverChanges]);
        };

        applyCommands(list, [[UPDATE, 20, { name: false }]]);

        expect(calls.length).toBe(1);
        expect(calls[0][0]).toEqual({});
        expect(calls[0][1]).toEqual({ name: false });
    });

    test("emits UPDATE command in _commands", () => {
        const list = makeList();
        addRecord(list, 30);
        list.fields = { name: { type: "char" } };

        applyCommands(list, [[UPDATE, 30, { name: "Changed" }]]);

        const updateCmds = list._commands.filter(
            (/** @type {any} */ c) => c[0] === UPDATE,
        );
        expect(updateCmds.length).toBe(1);
    });

    test("deduplicates UPDATE: second UPDATE is redundant when first already emitted", () => {
        const list = makeList();
        addRecord(list, 40);
        list.fields = { name: { type: "char" } };

        applyCommands(list, [
            [UPDATE, 40, { name: "First" }],
            [UPDATE, 40, { name: "Second" }],
        ]);

        const updateCmds = list._commands.filter(
            (/** @type {any} */ c) => c[0] === UPDATE,
        );
        expect(updateCmds.length).toBe(1);
    });
});

describe("applyCommands — CREATE", () => {
    test("adds a new virtual record to records and _currentIds", () => {
        const list = makeList();

        applyCommands(list, [[CREATE, false, { name: "New" }]]);

        expect(list.records.length).toBe(1);
        expect(list.records[0].resId).toBe(false);
        expect(list.count).toBe(1);
        expect(list._currentIds.length).toBe(1);
        expect(typeof list._currentIds[0]).toBe("string");
    });

    test("emits CREATE command in _commands", () => {
        const list = makeList();

        applyCommands(list, [[CREATE, false, { name: "New" }]]);

        const createCmds = list._commands.filter(
            (/** @type {any} */ c) => c[0] === CREATE,
        );
        expect(createCmds.length).toBe(1);
    });

    test("multiple CREATE commands produce multiple virtual records", () => {
        const list = makeList();

        applyCommands(list, [
            [CREATE, false, { name: "A" }],
            [CREATE, false, { name: "B" }],
        ]);

        expect(list.records.length).toBe(2);
        expect(list._currentIds[0]).not.toBe(list._currentIds[1]);
    });
});

describe("applyCommands — re-adding within one batch", () => {
    // Found by mutation: deleting `readdedIds.delete(id)` from the removal
    // handler broke nothing in 805 model tests. `readdedIds` is per-batch, so
    // only a LINK/UNLINK/LINK sequence inside ONE call reaches the interaction:
    // the second LINK is skipped unless the removal forgot the first one, and
    // the batch then drops the single remaining entry as the pending removal.
    test("LINK, UNLINK then LINK again on the same id keeps the record", () => {
        const list = makeList();

        applyCommands(list, [
            [LINK, 5, false],
            [UNLINK, 5, false],
            [LINK, 5, false],
        ]);

        expect(list._currentIds).toEqual([5]);
        expect(list.count).toBe(1);
        expect(list.records.map((/** @type {any} */ r) => r.resId)).toEqual([5]);
    });

    test("LINK then UNLINK in one batch leaves nothing behind", () => {
        const list = makeList();

        applyCommands(list, [
            [LINK, 5, false],
            [UNLINK, 5, false],
        ]);

        expect(list._currentIds).toEqual([]);
        expect(list.count).toBe(0);
    });
});

describe("applyCommands — command log integrity", () => {
    test("preserves existing _commands from prior operations", () => {
        const list = makeList();
        addRecord(list, 1);
        list._commands = [[CREATE, "virtual_1"]];
        const fakeVirtual = {
            resId: false,
            _virtualId: "virtual_1",
            activeFields: {},
            data: {},
            _applyChanges() {},
            _parseServerValues: (/** @type {any} */ v) => v,
        };
        list.records.push(fakeVirtual);
        list._currentIds.push("virtual_1");
        list._cache["virtual_1"] = fakeVirtual;

        applyCommands(list, [[DELETE, 1]]);

        expect(list._commands.some((/** @type {any} */ c) => c[0] === CREATE)).toBe(
            true,
        );
        expect(list._commands.some((/** @type {any} */ c) => c[0] === DELETE)).toBe(
            true,
        );
    });

    test("command order is preserved by index", () => {
        const list = makeList();
        addRecord(list, 2);
        addRecord(list, 3);
        addRecord(list, 4);

        applyCommands(list, [
            [DELETE, 2],
            [DELETE, 3],
            [DELETE, 4],
        ]);

        const deletedIds = list._commands.map((/** @type {any} */ c) => c[1]);
        expect(deletedIds).toEqual([2, 3, 4]);
    });

    test("DELETE/UNLINK prunes stashed _unknownRecordCommands for that id", () => {
        const list = makeList();
        applyCommands(list, [[UPDATE, 99, { name: "stashed" }]]);
        expect(99 in list._unknownRecordCommands).toBe(true);

        applyCommands(list, [[DELETE, 99]]);
        expect(99 in list._unknownRecordCommands).toBe(false);

        applyCommands(list, [[UPDATE, 77, { name: "stashed" }]]);
        expect(77 in list._unknownRecordCommands).toBe(true);
        applyCommands(list, [[UNLINK, 77]]);
        expect(77 in list._unknownRecordCommands).toBe(false);
    });
});

describe("applyCommands — SET and CLEAR", () => {
    test("a bare CLEAR empties the list", () => {
        const list = makeList();
        addRecord(list, 1);
        addRecord(list, 2);

        applyCommands(list, [[CLEAR, false, false]]);

        expect(list.records.length).toBe(0);
        expect(list._currentIds).toEqual([]);
        expect(list.count).toBe(0);
        expect(list._commands).toEqual([[CLEAR, false, false]]);
    });

    test("CLEAR then LINK keeps only the re-declared ids", () => {
        const list = makeList();
        addRecord(list, 1);
        addRecord(list, 2);

        applyCommands(list, [
            [CLEAR, false, false],
            [LINK, 2, { id: 2 }],
        ]);

        expect(list._currentIds).toEqual([2]);
        expect(list.count).toBe(1);
    });

    test("an UPDATE after CLEAR re-declares membership instead of dropping the row", () => {
        const list = makeList();
        addRecord(list, 1);
        addRecord(list, 2);

        applyCommands(list, [
            [CLEAR, false, false],
            [UPDATE, 1, { name: "kept" }],
        ]);

        expect(list._currentIds).toEqual([1]);
        expect(list.count).toBe(1);
        expect(list._cache[1].data.name).toBe("kept");
        expect(list._commands).toEqual([
            [CLEAR, false, false],
            [LINK, 1, false],
            [UPDATE, 1],
        ]);
    });

    test("SET is applied as the CLEAR + LINK sequence it means", () => {
        const SET = 6;
        const list = makeList();
        addRecord(list, 1);
        addRecord(list, 2);

        applyCommands(list, [[SET, false, [2, 3]]]);

        expect(list._currentIds).toEqual([2, 3]);
        expect(list.count).toBe(2);
    });

    test("a malformed command is still ignored with a console warning", () => {
        const list = makeList();
        addRecord(list, 1);

        const warnings = [];
        const originalWarn = console.warn;
        console.warn = (...args) => warnings.push(args.join(" "));
        try {
            applyCommands(list, [[37, false, false]]);
        } finally {
            console.warn = originalWarn;
        }

        expect(warnings.length).toBe(1);
        expect(warnings[0]).toInclude("unhandled x2many command 37");
        expect(list._currentIds).toEqual([1]);
    });

    test("a CREATE echoing a virtual id the list owns reuses that row", () => {
        const list = makeList();
        applyCommands(list, [[CREATE, false, { name: "typed" }]]);
        const virtualId = list.records[0]._virtualId;

        applyCommands(list, [
            [CLEAR, false, false],
            [CREATE, virtualId, { name: "echoed" }],
        ]);

        expect(list.records.length).toBe(1);
        expect(list._currentIds).toEqual([virtualId]);
        expect(
            list._commands.filter((/** @type {any} */ c) => c[0] === CREATE).length,
        ).toBe(1);
    });
});

describe("applyCommands — record loading", () => {
    test("server returning fewer records than requested does not misassign values", async () => {
        const list = makeList({
            model: {
                _patchConfig: () => {},
                _loadRecords: ({ /** @type {any} */ resIds }) => {
                    expect(resIds).toEqual([1, 2, 3]);
                    return Promise.resolve([
                        { id: 1, name: "One" },
                        { id: 3, name: "Three" },
                    ]);
                },
            },
        });

        await applyCommands(list, [
            [LINK, 1],
            [LINK, 2],
            [LINK, 3],
        ]);

        expect(list._cache[1].data).toEqual({ id: 1, name: "One" });
        expect(list._cache[3].data).toEqual({ id: 3, name: "Three" });
        expect(list._cache[2].data.id).toBe(2);
        expect(list._cache[2].data.name).toBe(undefined);
    });
});
