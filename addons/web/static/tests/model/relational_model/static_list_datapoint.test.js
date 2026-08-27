// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { markRaw } from "@odoo/owl";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { ListMembership } from "@web/model/relational_model/list_membership";
import { StaticList } from "@web/model/relational_model/static_list";
import { sortStaticList } from "@web/model/relational_model/static_list_sort";

describe("extendRecord fields identity", () => {
    test("keeps the extended record's config.fields === list.fields", async () => {
        const listFields = { display_name: { type: "char", name: "display_name" } };
        const list = Object.create(StaticList.prototype);
        Object.assign(list, {
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
        _membership: new ListMembership(),
        _config: {
            activeFields: {},
            fields: { name: { type: "char" } },
            resModel: "res.partner",
            context: {},
            relationField: false,
        },
        _cache: markRaw(new Map()),
        _unknownRecordCommands: new Map(),
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
        list._cache.set(1, dirty);

        const out = list._createRecordDatapoint(
            { id: 1, name: "reloaded" },
            { activeFields: {} },
        );

        expect(out).toBe(dirty);
        expect(list._cache.get(1)).toBe(dirty);
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
        list._cache.set(2, clean);

        const out = list._createRecordDatapoint({ id: 2, name: "Y" });

        expect(out).not.toBe(clean);
        expect(out.constructedByClass).toBe(true);
        expect(list._cache.get(2)).toBe(out);
    });
});

describe("sort restricted-field reload preserves dirty datapoint", () => {
    test("dirty record keeps its _changes across a sort reload", async () => {
        const list = Object.create(StaticList.prototype);
        Object.assign(list, {
            _membership: new ListMembership(),
            _config: {
                activeFields: { name: makeActiveField(), other: makeActiveField() },
                fields: { name: { type: "char" }, other: { type: "char" } },
                resModel: "res.partner",
                context: {},
                orderBy: [],
            },
            _cache: markRaw(new Map()),
            _unknownRecordCommands: new Map(),
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
        list._cache.set(1, dirty);

        await sortStaticList(list, [1], [{ name: "name", asc: true }]);

        expect(list._cache.get(1)).toBe(dirty);
        expect(dirty._changes.other).toBe("PENDING_UPDATE");
        expect(dirty.data.name).toBe("A");
        expect(list._loadCalled).toBe(true);
    });
});

function makeBareStaticList({ records = [], handleField = "sequence" } = {}) {
    const list = Object.create(StaticList.prototype);
    Object.assign(list, {
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
