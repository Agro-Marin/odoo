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
import { StaticList } from "@web/model/relational_model/static_list";
import { sort } from "@web/model/relational_model/static_list_sort";

// extendRecord — config.fields identity

describe("extendRecord fields identity", () => {
    test("keeps the extended record's config.fields === list.fields", async () => {
        const listFields = { display_name: { type: "char", name: "display_name" } };
        const list = Object.create(StaticList.prototype);
        Object.assign(list, {
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

        // A record that has already been extended once (case 1.1: the simplest
        // path — patch config + savepoint). Its config.fields starts as a
        // DIFFERENT object from the list's.
        const record = {
            id: 1,
            config: {
                activeFields: { display_name: makeActiveField() },
                fields: { display_name: { type: "char", name: "display_name" } },
            },
            _addSavePoint() {},
        };
        list._extendedRecords.add(record.id);

        // The caller passes its OWN fields snapshot (yet another object).
        const paramsFields = { display_name: { type: "char", name: "display_name" } };
        await list.extendRecord(
            {
                activeFields: { display_name: makeActiveField() },
                fields: paramsFields,
            },
            record,
        );

        // config.fields must be the list's live merged object, not the snapshot.
        expect(record.config.fields).toBe(list.fields);
        expect(record.config.fields).not.toBe(paramsFields);
    });
});

// _createRecordDatapoint — dirty datapoints are merged, not replaced

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

        // Same datapoint returned & still cached — NOT replaced.
        expect(out).toBe(dirty);
        expect(list._cache[1]).toBe(dirty);
        // Its pending _changes survive (so serializeCommands still emits them).
        expect(dirty._changes.child_ids).toBe("PENDING_UPDATE");
        // The freshly-loaded values were merged via _applyValues.
        expect(dirty.appliedWith).toEqual({ id: 1, name: "reloaded" });
    });

    test("still replaces a cached CLEAN datapoint (guard is scoped to dirty)", () => {
        const list = makeBareList();
        const clean = {
            resId: 2,
            dirty: false,
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

// sort() — a dirty datapoint survives a restricted-field reload

describe("sort restricted-field reload preserves dirty datapoint", () => {
    test("dirty record keeps its _changes across a sort reload", async () => {
        const list = Object.create(StaticList.prototype);
        Object.assign(list, {
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
                // Restricted-field load returns only the orderBy field.
                _loadRecords: async () => [{ id: 1, name: "A" }],
            },
            _load: async () => {
                list._loadCalled = true;
            },
            // Force the dirty record to be (re)loaded: it lacks the sort field.
            _getResIdsToLoad: () => [1],
        });

        const dirty = {
            resId: 1,
            _virtualId: null,
            dirty: true,
            _changes: { other: "PENDING_UPDATE" },
            data: { name: "" },
            _applyValues(data) {
                Object.assign(this.data, data);
            },
        };
        list._cache[1] = dirty;

        await sort(list, [1], [{ name: "name", asc: true }]);

        // The dirty datapoint was merged, not replaced.
        expect(list._cache[1]).toBe(dirty);
        // Its pending command survives → would still serialize on save.
        expect(dirty._changes.other).toBe("PENDING_UPDATE");
        // The freshly-loaded sort value was merged in.
        expect(dirty.data.name).toBe("A");
        expect(list._loadCalled).toBe(true);
    });
});
