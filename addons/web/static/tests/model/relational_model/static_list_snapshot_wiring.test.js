// @ts-check

/**
 * Wiring tests for the ``StaticList._snapshot`` / ``_restore`` pair.
 *
 * ``static_list_rollback_completeness.test.js`` pins WHAT the pair restores.
 * This file pins WHO calls it: each of ``RelationalRecord._update``'s three
 * failure paths must roll every x2many in the changeset back, and
 * ``StaticList._discard`` must go through the same primitive when a savepoint
 * exists instead of hand-rolling a narrower restore.
 */

import { describe, expect, test } from "@odoo/hoot";
import { markRaw } from "@odoo/owl";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { RelationalRecord } from "@web/model/relational_model/record";
import { RecordEditState } from "@web/model/relational_model/record_edit_state";
import { StaticList } from "@web/model/relational_model/static_list";

/** A stand-in x2many list that records snapshot/restore traffic. */
function makeSpyList() {
    return {
        _commands: [],
        _currentIds: [],
        count: 0,
        snapshots: 0,
        restores: 0,
        _snapshot() {
            this.snapshots++;
            return { token: this.snapshots };
        },
        _restore(snapshot) {
            this.restores++;
            this.restored = snapshot;
        },
        // ``preprocessX2manyChanges`` applies the change's command list to the
        // live datapoint before ``_update`` commits anything.
        async _applyCommands() {},
        async _replaceWith() {},
    };
}

/** @param {{ failIn?: "preprocess" | "onchange" | "onUpdate" }} [options] */
function makeRecordWithList({ failIn } = {}) {
    const record = Object.create(RelationalRecord.prototype);
    const list = makeSpyList();
    const urgentSave = {
        isActive: false,
        awaitUnlessUrgent: (prom) =>
            failIn === "preprocess" ? Promise.reject(new Error("boom")) : prom,
        unlessUrgent: (fn) => fn(),
    };
    Object.assign(record, {
        _config: {
            resModel: "some.model",
            context: {},
            activeFields: { line_ids: makeActiveField() },
            fields: { line_ids: { type: "one2many", name: "line_ids" } },
        },
        data: { line_ids: list },
        _editState: new RecordEditState(),
        selected: false,
        model: {
            urgentSave,
            multiEdit: false,
            hasOnRecordChangedHook: false,
            hooks: { ui: { onDisplayInvalidFields: () => () => {} } },
        },
        _setEvalContext() {},
        _parseServerValues: (values) => ({ ...values }),
        _getTextValues: () => ({}),
        _isInvisible: () => false,
        _isRequired: () => false,
        _isReadonly: () => false,
        _onUpdate: async () => {
            if (failIn === "onUpdate") {
                throw new Error("boom");
            }
        },
        _getOnchangeValues: async () => {
            if (failIn === "onchange") {
                throw new Error("boom");
            }
            return {};
        },
    });
    return { record, list };
}

describe("_update rolls x2many state back through _restore", () => {
    for (const failIn of /** @type {const} */ ([
        "preprocess",
        "onchange",
        "onUpdate",
    ])) {
        test(`a ${failIn} failure restores the list snapshot`, async () => {
            const { record, list } = makeRecordWithList({ failIn });

            // A field widget hands ``_update`` a COMMAND LIST; the live list
            // datapoint it applies to is ``record.data.line_ids``.
            await expect(
                record._update({ line_ids: [[4, 5, false]] }),
            ).rejects.toThrow();

            expect(list.snapshots).toBeGreaterThan(0);
            expect(list.restores).toBeGreaterThan(0);
        });
    }

    test("a successful update restores nothing", async () => {
        const { record, list } = makeRecordWithList();

        await record._update({ line_ids: [[4, 5, false]] });

        expect(list.snapshots).toBeGreaterThan(0);
        expect(list.restores).toBe(0);
    });
});

describe("_discard restores the savepoint's page limit", () => {
    function makeList() {
        const list = Object.create(StaticList.prototype);
        Object.assign(list, {
            _config: {
                limit: 2,
                offset: 0,
                resIds: [1, 2],
                orderBy: [],
                resModel: "res.partner",
                context: {},
                activeFields: {},
                fields: {},
            },
            records: [],
            count: 2,
            _cache: markRaw({}),
            _commands: [],
            _initialCommands: [],
            _commandsPromise: null,
            _savePoint: undefined,
            _unknownRecordCommands: {},
            _loadingStubIds: new Set(),
            _currentIds: [1, 2],
            _tmpIncreaseLimit: 0,
            _needsReordering: false,
            _extendedRecords: new Set(),
            _onUpdate: async () => {},
            model: {
                _patchConfig: (config, patch) => Object.assign(config, patch),
                _loadRecords: async () => [],
            },
        });
        for (const id of [1, 2, 3]) {
            list._cache[id] = {
                resId: id,
                _virtualId: false,
                _discard() {},
                _addSavePoint() {},
            };
        }
        return list;
    }

    test("a slot opened before the savepoint survives the discard", () => {
        const list = makeList();
        // The user adds a third row: one temporary slot, opened BEFORE any
        // dialog is opened on the list.
        list._bumpLimit(1);
        list._currentIds = [1, 2, 3];
        list.count = 3;
        expect(list.limit).toBe(3);

        // Opening a form dialog on a row snapshots the list...
        list._addSavePoint();
        // ...and the dialog opens a further slot.
        list._bumpLimit(1);
        expect(list.limit).toBe(4);

        // Discarding the dialog must undo the dialog's slot only.
        list._discard();

        expect(list.limit).toBe(3);
        expect(list._tmpIncreaseLimit).toBe(1);
        expect(list._currentIds).toEqual([1, 2, 3]);
        expect(list.records).toHaveLength(3);
    });

    test("without a savepoint every temporary slot is forfeit", () => {
        const list = makeList();
        list._bumpLimit(1);
        list._currentIds = [1, 2, 3];
        list.count = 3;

        list._discard();

        expect(list.limit).toBe(2);
        expect(list._tmpIncreaseLimit).toBe(0);
        expect(list._currentIds).toEqual([1, 2]);
    });
});
