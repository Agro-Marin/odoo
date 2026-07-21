// @ts-check

/**
 * Unit tests for applyCommands (static_list_command_engine.js): applies x2many
 * ORM commands (CREATE/UPDATE/DELETE/UNLINK/LINK) to a StaticList-shaped mock —
 * no OWL/DOM/mock server. It mutates its first argument, so assertions read
 * the mutated list state.
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
        _loadingStubIds: new Set(),
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
                // Mirrors RelationalRecord._applyChanges(changes, serverChanges):
                // slot 1 takes already-parsed user changes, slot 2 takes RAW
                // server values which the record parses itself.
                _applyChanges(changes, serverChanges = {}) {
                    Object.assign(
                        this.data,
                        changes,
                        this._parseServerValues(serverChanges),
                    );
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
        // Mirrors StaticList._bumpLimit: cumulative temp-limit bump used when
        // commands add records beyond the current page limit.
        _bumpLimit(n) {
            this._tmpIncreaseLimit += n;
            this.model._patchConfig(this.config, { limit: this.limit + n });
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
        // Same two-slot contract as the makeList mock above.
        _applyChanges(changes, serverChanges = {}) {
            Object.assign(this.data, changes, this._parseServerValues(serverChanges));
        },
        _applyValues(values) {
            if (values) {
                Object.assign(this.data, values);
            }
        },
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

    test("an UNLINK absorbed into a staged SET still drops membership", () => {
        // Regression: absorbing an UNLINK into a staged SET (m2m replaceWith
        // then forget on the same field) removed the id from the SET payload
        // but `break`-ed before marking removedIds — so the row kept
        // rendering and count drifted from the relation. The absorb only
        // fixes the save payload; membership must still update.
        const SET = 6;
        const list = makeList();
        list._commands = [[SET, false, [1, 2, 3]]];
        addRecord(list, 1);
        addRecord(list, 2);
        addRecord(list, 3);
        expect(list.count).toBe(3);

        applyCommands(list, [[UNLINK, 2]]);

        // Absorbed from the SET payload...
        expect(list._commands[0]).toEqual([SET, false, [1, 3]]);
        // ...AND removed from the visible list / membership / count.
        expect(list._currentIds).toEqual([1, 3]);
        expect(list.records.map((r) => r.resId)).toEqual([1, 3]);
        expect(list.count).toBe(2);
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

        applyCommands(list, [[LINK, 5]]);

        expect(list.count).toBe(initialCount);
        expect(list.records.length).toBe(1); // unchanged
    });

    test("re-links a previously deleted record (DELETE then LINK)", () => {
        const list = makeList();
        addRecord(list, 15);

        applyCommands(list, [
            [DELETE, 15],
            [LINK, 15],
        ]);

        // After DELETE, 15 is in removedIds; then LINK sees it's NOT in
        // _currentIds (was just removed), so it adds it back.
        expect(list._currentIds).toInclude(15);
    });

    test("a displayed LINK is inserted at its page position, not the tail", () => {
        // Regression: LINK pushed the id to the END of _currentIds while
        // rendering the row on the CURRENT page. On a multi-page x2many the
        // row showed here now but belonged to the last page, so it jumped
        // pages on the next load and evalContext currentIds order disagreed
        // with the display. Membership must match the display position.
        const list = makeList();
        list.limit = 3; // room for one more on the current page
        list.offset = 0;
        // Membership spans two pages (90, 91 belong to later positions).
        addRecord(list, 1);
        addRecord(list, 2);
        list._currentIds = [1, 2, 90, 91];
        list.count = 4;

        applyCommands(list, [[LINK, 9, { id: 9, display_name: "Rec 9" }]]);

        // The row renders at the end of the current page (index offset +
        // records.length - 1 = 2), so its id lands there in membership — NOT
        // appended after the page-2 ids.
        expect(list._currentIds).toEqual([1, 2, 9, 90, 91]);
        expect(list.records.map((r) => r.resId)).toEqual([1, 2, 9]);
    });

    test("a LINK past the page limit appends to membership (not displayed)", () => {
        const list = makeList();
        list.limit = 2;
        list.offset = 0;
        addRecord(list, 1);
        addRecord(list, 2);
        list._currentIds = [1, 2];
        list.count = 2;

        // No display data → not shown this page (over limit, canAddOverLimit
        // false) → tail push.
        applyCommands(list, [[LINK, 9]]);

        expect(list._currentIds).toEqual([1, 2, 9]);
        expect(list.records.map((r) => r.resId)).toEqual([1, 2]);
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

        expect(list._unknownRecordCommands[99]).toEqual([
            [UPDATE, 99, { name: "Ghost" }],
        ]);
    });

    test("stashes only the invisible sub-x2many slice, applies the rest", () => {
        // Regression: the whole command used to be stashed when ONE of its
        // fields was an always-invisible / non-active sub-x2many. Only that
        // field's slice may be deferred — the stash shadows the record's own
        // changeset at serialize time, so over-stashing dropped later user
        // edits to the row from the save payload.
        const list = makeList();
        const record = addRecord(list, 20);
        list.fields = {
            name: { type: "char" },
            lines: { type: "one2many" },
        };
        record.activeFields = {
            name: {},
            // `lines` is NOT in activeFields: its slice must be deferred.
        };

        applyCommands(list, [[UPDATE, 20, { name: "Updated", lines: [[5, 0, 0]] }]]);

        // The visible scalar was applied to the record...
        expect(record.data.name).toBe("Updated");
        // ...and only the sub-x2many slice was stashed.
        expect(list._unknownRecordCommands[20]).toEqual([
            [UPDATE, 20, { lines: [[5, 0, 0]] }],
        ]);
    });

    test("a later UPDATE to a LOADED record with a deferred slice applies live", () => {
        // Regression: once a loaded record had an invisible-sub-x2many slice
        // stashed in _unknownRecordCommands, EVERY later UPDATE for it was
        // misrouted to the stash (the `id in _unknownRecordCommands` branch),
        // leaving the visible row stale until save. The stash is only for
        // still-LOADING stubs (tracked in _loadingStubIds); a loaded record's
        // scalar updates must apply immediately.
        const list = makeList();
        const record = addRecord(list, 20);
        list.fields = {
            name: { type: "char" },
            lines: { type: "one2many" },
        };
        record.activeFields = { name: {} }; // `lines` not active → slice deferred

        // Onchange #1: stashes the invisible sub-x2many slice.
        applyCommands(list, [[UPDATE, 20, { name: "First", lines: [[5, 0, 0]] }]]);
        expect(record.data.name).toBe("First");
        expect(list._unknownRecordCommands[20]).toEqual([
            [UPDATE, 20, { lines: [[5, 0, 0]] }],
        ]);
        expect(list._loadingStubIds.has(20)).toBe(false);

        // Onchange #2: a plain scalar UPDATE must reach the live record, not
        // the stash.
        applyCommands(list, [[UPDATE, 20, { name: "Second" }]]);
        expect(record.data.name).toBe("Second");
        // The deferred slice is untouched; the scalar was NOT stashed.
        expect(list._unknownRecordCommands[20]).toEqual([
            [UPDATE, 20, { lines: [[5, 0, 0]] }],
        ]);
    });

    test("routes UPDATE payloads through the SERVER slot of _applyChanges, unparsed", () => {
        // Regression: the engine used to pre-parse the payload and pass it as
        // the USER-changes slot (first argument). For a char/text the server
        // set to false, the user slot stored the parsed "" in _textValues, so
        // a row modifier like [("field", "=", False)] mis-evaluated until
        // reload. The server slot (second argument) parses the values itself
        // and snapshots them RAW, preserving false-vs-"" provenance.
        const list = makeList();
        const record = addRecord(list, 20);
        list.fields = { name: { type: "char" } };
        record.activeFields = { name: {} };
        const calls = [];
        record._applyChanges = (changes, serverChanges = {}) => {
            calls.push([changes, serverChanges]);
        };

        applyCommands(list, [[UPDATE, 20, { name: false }]]);

        expect(calls.length).toBe(1);
        // User slot empty; raw (unparsed) server value in the server slot.
        expect(calls[0][0]).toEqual({});
        expect(calls[0][1]).toEqual({ name: false });
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
            resId: false,
            _virtualId: "virtual_1",
            activeFields: {},
            data: {},
            _applyChanges() {},
            _parseServerValues: (v) => v,
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
        applyCommands(list, [
            [DELETE, 2],
            [DELETE, 3],
            [DELETE, 4],
        ]);

        const deletedIds = list._commands.map((c) => c[1]);
        expect(deletedIds).toEqual([2, 3, 4]);
    });

    test("DELETE/UNLINK prunes stashed _unknownRecordCommands for that id", () => {
        // Record 99 is on an unloaded page (not in _cache): its UPDATE is
        // stashed in _unknownRecordCommands to replay if it ever loads.
        const list = makeList();
        applyCommands(list, [[UPDATE, 99, { name: "stashed" }]]);
        expect(99 in list._unknownRecordCommands).toBe(true);

        // Removing it must drop the stash — otherwise a later page-fill that
        // re-loads resId 99 would replay the stale UPDATE and resurrect values
        // for a record the user deleted.
        applyCommands(list, [[DELETE, 99]]);
        expect(99 in list._unknownRecordCommands).toBe(false);

        // Same for UNLINK.
        applyCommands(list, [[UPDATE, 77, { name: "stashed" }]]);
        expect(77 in list._unknownRecordCommands).toBe(true);
        applyCommands(list, [[UNLINK, 77]]);
        expect(77 in list._unknownRecordCommands).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// Unhandled commands (SET / CLEAR)
// ---------------------------------------------------------------------------

describe("applyCommands — unhandled commands", () => {
    test("SET and CLEAR are ignored with a console warning", () => {
        const SET = 6;
        const CLEAR = 5;
        const list = makeList();
        addRecord(list, 1);

        const warnings = [];
        const originalWarn = console.warn;
        console.warn = (...args) => warnings.push(args.join(" "));
        try {
            applyCommands(list, [
                [SET, false, [1, 2]],
                [CLEAR, false, false],
            ]);
        } finally {
            console.warn = originalWarn;
        }

        // SET is normally routed around the engine (preprocessX2manyChanges →
        // _replaceWith); a raw server command list landing here must be loud,
        // not silently dropped.
        expect(warnings.length).toBe(2);
        expect(warnings[0]).toInclude("unhandled x2many command 6");
        expect(warnings[1]).toInclude("unhandled x2many command 5");
        // The list itself is untouched.
        expect(list.records.length).toBe(1);
        expect(list._currentIds).toEqual([1]);
        expect(list._commands).toEqual([]);
    });
});

// ---------------------------------------------------------------------------
// Record loading (page fill / LINK without data)
// ---------------------------------------------------------------------------

describe("applyCommands — record loading", () => {
    test("server returning fewer records than requested does not misassign values", async () => {
        // Simulate a concurrent deletion: 3 ids are requested but the server
        // only returns values for 1 and 3 (record 2 was deleted server-side).
        const list = makeList({
            model: {
                _patchConfig: () => {},
                _loadRecords: ({ resIds }) => {
                    expect(resIds).toEqual([1, 2, 3]);
                    return Promise.resolve([
                        { id: 1, name: "One" },
                        { id: 3, name: "Three" },
                    ]);
                },
            },
        });

        // LINK without data (command[2]) pushes the records to recordsToLoad
        await applyCommands(list, [
            [LINK, 1],
            [LINK, 2],
            [LINK, 3],
        ]);

        // Surviving records got their own values
        expect(list._cache[1].data).toEqual({ id: 1, name: "One" });
        expect(list._cache[3].data).toEqual({ id: 3, name: "Three" });
        // The missing record must NOT receive another record's values
        // (index-based fallback would merge { id: 3, name: "Three" } into it)
        expect(list._cache[2].data.id).toBe(2);
        expect(list._cache[2].data.name).toBe(undefined);
    });
});
