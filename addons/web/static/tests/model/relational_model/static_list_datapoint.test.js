// @ts-check

/**
 * Tests two StaticList datapoint-lifecycle fixes:
 *  - ``extendRecord`` keeps the extended record's ``config.fields`` identical to
 *    the list's live ``fields`` object, not a caller/param snapshot, so mutations
 *    don't diverge.
 *  - ``_createRecordDatapoint`` merges into (never replaces) a cached datapoint
 *    with pending ``_changes``, so a restricted-field reload (e.g. ``sort()``)
 *    doesn't drop them.
 *
 * Uses ``Object.create(StaticList.prototype)`` against a hand-built state,
 * mirroring static_list_pending_commands.test.js.
 */

import { describe, expect, test } from "@odoo/hoot";
import { markRaw } from "@odoo/owl";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { ListMembership } from "@web/model/relational_model/list_membership";
import { StaticList } from "@web/model/relational_model/static_list";
import { sort } from "@web/model/relational_model/static_list_sort";

describe("extendRecord fields identity", () => {
    test("keeps the extended record's config.fields === list.fields", async () => {
        const listFields = { display_name: { type: "char", name: "display_name" } };
        const list = Object.create(StaticList.prototype);
        Object.assign(list, {
            // Membership owner first: the keys below write through its accessors.
            _membership: new ListMembership(),
            _config: {
                activeFields: { display_name: makeActiveField() },
                fields: listFields,
                resModel: "res.partner",
                context: {},
            },
            _extendedRecords: new Set(),
            model: {
                mutex: { exec: (fn) => fn() },
                _patchConfig: (config, patch) => Object.assign(config, patch),
            },
        });

        const record = {
            id: 1,
            config: {
                activeFields: { display_name: makeActiveField() },
                fields: { display_name: { type: "char", name: "display_name" } },
            },
            _addSavePoint() {},
            extendActiveFields() {},
        };
        list._extendedRecords.add(record.id);

        const paramsFields = { display_name: { type: "char", name: "display_name" } };
        await list.extendRecord(
            {
                activeFields: { display_name: makeActiveField() },
                fields: paramsFields,
            },
            record,
        );

        expect(record.config.fields).toBe(list.fields);
        expect(record.config.fields).not.toBe(paramsFields);
    });
});

/** Minimal fake Record class for the clean-replacement path. */
class FakeRecord {
    constructor(model, config, data, options) {
        this.config = config;
        this.data = data;
        this.resId = data.id || false;
        this._virtualId = options.virtualId;
        this.dirty = false;
        this._changes = {};
        this.constructedByClass = true;
    }
}

function makeBareList() {
    const list = Object.create(StaticList.prototype);
    Object.assign(list, {
        // Membership owner first: the keys below write through its accessors.
        _membership: new ListMembership(),
        _config: {
            activeFields: {},
            fields: { name: { type: "char" } },
            resModel: "res.partner",
            context: {},
            relationField: false,
        },
        _cache: markRaw({}),
        _unknownRecordCommands: {},
        _parent: {},
        model: { Class: { Record: FakeRecord } },
    });
    return list;
}

describe("_createRecordDatapoint dirty-merge guard", () => {
    test("merges into a cached dirty datapoint instead of replacing it", () => {
        const list = makeBareList();
        const dirty = {
            resId: 1,
            _virtualId: null,
            dirty: true,
            hasPendingChanges: true,
            _changes: { child_ids: "PENDING_UPDATE" },
            appliedWith: null,
            _applyValues(data) {
                this.appliedWith = data;
            },
        };
        list._cache[1] = dirty;

        const out = list._createRecordDatapoint(
            { id: 1, name: "reloaded" },
            { activeFields: {} },
        );

        expect(out).toBe(dirty);
        expect(list._cache[1]).toBe(dirty);
        expect(dirty._changes.child_ids).toBe("PENDING_UPDATE");
        expect(dirty.appliedWith).toEqual({ id: 1, name: "reloaded" });
    });

    test("still replaces a cached CLEAN datapoint (guard is scoped to dirty)", () => {
        const list = makeBareList();
        const clean = {
            resId: 2,
            dirty: false,
            hasPendingChanges: false,
            _changes: {},
            _applyValues() {
                throw new Error("clean records must be replaced, not merged");
            },
        };
        list._cache[2] = clean;

        const out = list._createRecordDatapoint({ id: 2, name: "Y" });

        expect(out).not.toBe(clean);
        expect(out.constructedByClass).toBe(true);
        expect(list._cache[2]).toBe(out);
    });
});

describe("sort restricted-field reload preserves dirty datapoint", () => {
    test("dirty record keeps its _changes across a sort reload", async () => {
        const list = Object.create(StaticList.prototype);
        Object.assign(list, {
            // Membership owner first: the keys below write through its accessors.
            _membership: new ListMembership(),
            _config: {
                activeFields: { name: makeActiveField(), other: makeActiveField() },
                fields: { name: { type: "char" }, other: { type: "char" } },
                resModel: "res.partner",
                context: {},
                orderBy: [],
            },
            _cache: markRaw({}),
            _unknownRecordCommands: {},
            _parent: {},
            _needsReordering: true,
            model: {
                _loadRecords: async () => [{ id: 1, name: "A" }],
            },
            _load: async () => {
                list._loadCalled = true;
            },
            _getResIdsToLoad: () => [1],
        });

        const dirty = {
            resId: 1,
            _virtualId: null,
            dirty: true,
            hasPendingChanges: true,
            _changes: { other: "PENDING_UPDATE" },
            data: { name: "" },
            _applyValues(data) {
                Object.assign(this.data, data);
            },
        };
        list._cache[1] = dirty;

        await sort(list, [1], [{ name: "name", asc: true }]);

        expect(list._cache[1]).toBe(dirty);
        expect(dirty._changes.other).toBe("PENDING_UPDATE");
        expect(dirty.data.name).toBe("A");
        expect(list._loadCalled).toBe(true);
    });
});

/**
 * Bare StaticList with no collaborator methods defined at all: if
 * _duplicateRecords fails to short-circuit on its early-return guard, it
 * calls one of them (e.g. `this._createNewRecordDatapoint`) and that throws
 * "is not a function" — the natural signal that the guard didn't hold,
 * with no manual instrumentation needed.
 */
function makeBareStaticList({ records = [], handleField = "sequence" } = {}) {
    const list = Object.create(StaticList.prototype);
    Object.assign(list, {
        // Membership owner first: the keys below write through its accessors.
        _membership: new ListMembership(),
        records,
        handleField,
    });
    return list;
}

describe("_duplicateRecords early-return guards", () => {
    test("no records to duplicate: returns without touching any collaborator", async () => {
        const list = makeBareStaticList({ records: [] });
        await list._duplicateRecords([], {});
        expect(list.records).toEqual([]);
    });

    test("no handleField to sequence on: returns without touching any collaborator", async () => {
        const records = [{ data: { sequence: 1 } }];
        const list = makeBareStaticList({ records, handleField: false });
        await list._duplicateRecords(records, {});
        expect(list.records).toBe(records);
    });
});
