// @ts-check

/**
 * ``extendRecord`` opens an x2many row in a sub-form: it widens the row's
 * active fields to the dialog's, parks the row's pending edits in a savepoint
 * so a cancel can restore them, and marks the row extended.
 * ``validateExtendedRecord`` is the confirm side.
 *
 * Its three exits deliberately do NOT do the same thing. A row confirmed
 * without a single edit returns early and keeps the widened active fields,
 * because narrowing them back is not free: the command engine defers an
 * onchange payload naming a field the row no longer declares
 * (``!(fieldName in record.activeFields)``) into ``_unknownRecordCommands``,
 * and ``extendRecord`` replays those only the FIRST time a row is extended.
 * A row that lost its widened fields therefore shows a stale sub-form for the
 * rest of the record's life.
 *
 * These tests pin that asymmetry so it is not "tidied up" again -- it reads
 * like an oversight and is not.
 */

import { describe, expect, test } from "@odoo/hoot";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { RelationalRecord } from "@web/model/relational_model/record";
import { StaticList } from "@web/model/relational_model/static_list";

function makeList() {
    /** @type {any[]} */
    const updates = [];
    const model = {
        Class: { Record: RelationalRecord, StaticList },
        mutex: { exec: (/** @type {any} */ fn) => Promise.resolve().then(fn) },
        multiEdit: false,
        hasOnRecordChangedHook: false,
        urgentSave: {
            isActive: false,
            awaitUnlessUrgent: (/** @type {any} */ prom) => prom,
            unlessUrgent: (/** @type {any} */ fn) => fn(),
        },
        _patchConfig: (/** @type {any} */ config, /** @type {any} */ patch) =>
            Object.assign(config, patch),
        _loadRecords: async (/** @type {any} */ { resIds }) =>
            resIds.map((/** @type {number} */ id) => ({ id, name: `row ${id}` })),
        _loadNewRecord: async () => ({ name: "" }),
    };
    const config = {
        resModel: "line",
        activeFields: { name: makeActiveField() },
        fields: { name: { type: "char", name: "name" } },
        relationField: false,
        offset: 0,
        limit: 10,
        resIds: [1, 2],
        orderBy: /** @type {any[]} */ ([]),
        context: {},
    };
    const list = new StaticList(
        /** @type {any} */ (model),
        /** @type {any} */ (config),
        [
            { id: 1, name: "row 1" },
            { id: 2, name: "row 2" },
        ],
        {
            parent: {
                evalContext: {},
                evalContextWithVirtualIds: {},
                _isEvalContextReady: true,
            },
            onUpdate: async () => updates.push("parent"),
        },
    );
    return { list, updates };
}

describe("validateExtendedRecord", () => {
    test("a member confirmed with no edits KEEPS its widened active fields", async () => {
        const { list, updates } = makeList();
        const record = list.records[0];
        const widened = /** @type {any} */ ({
            ...list.config.activeFields,
            note: makeActiveField(),
        });
        list.config.fields.note = { type: "char", name: "note" };
        list.model._patchConfig(record.config, { activeFields: widened });
        record._activeFieldsToRestore = { ...list.config.activeFields };

        await list.validateExtendedRecord(/** @type {any} */ (record));

        expect(Object.keys(record.activeFields).sort()).toEqual(["name", "note"]);
        expect(record._activeFieldsToRestore).not.toBe(/** @type {any} */ (undefined));
        // Nothing changed, so there is nothing to propagate upwards either.
        expect(updates).toEqual([]);
    });

    test("a member WITH pending changes ends the extended session", async () => {
        const { list, updates } = makeList();
        const record = list.records[0];
        const widened = /** @type {any} */ ({
            ...list.config.activeFields,
            note: makeActiveField(),
        });
        list.config.fields.note = { type: "char", name: "note" };
        list.model._patchConfig(record.config, { activeFields: widened });
        await record._update({ name: "edited" });
        record._addSavePoint();
        record._activeFieldsToRestore = { ...list.config.activeFields };
        updates.length = 0; // the edit itself already notified the parent

        await list.validateExtendedRecord(/** @type {any} */ (record));

        expect(Object.keys(record.activeFields)).toEqual(["name"]);
        expect(record._activeFieldsToRestore).toBe(/** @type {any} */ (undefined));
        expect(record._savePoint).toBe(/** @type {any} */ (undefined));
        expect(updates).toEqual(["parent"]);
        expect(record._changes.name).toBe("edited");
    });

    test("a record that is not yet a member is added, then ends the session", async () => {
        const { list, updates } = makeList();
        const record = await list._createNewRecordDatapoint({ manuallyAdded: true });
        record._addSavePoint();
        record._activeFieldsToRestore = { ...list.config.activeFields };

        await list.validateExtendedRecord(/** @type {any} */ (record));

        expect(list.currentIds).toInclude(record._virtualId);
        expect(list.count).toBe(3);
        expect(record._savePoint).toBe(/** @type {any} */ (undefined));
        expect(record._activeFieldsToRestore).toBe(/** @type {any} */ (undefined));
        expect(updates).toEqual(["parent"]);
    });
});
