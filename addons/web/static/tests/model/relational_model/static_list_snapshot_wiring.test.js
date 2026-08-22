// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { markRaw } from "@odoo/owl";
import { MODEL_LIFECYCLE_PROTO } from "@web/../tests/model/relational_model/model_doubles";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { ListMembership } from "@web/model/relational_model/list_membership";
import { RelationalRecord } from "@web/model/relational_model/record";
import { RecordEditState } from "@web/model/relational_model/record_edit_state";
import { StaticList } from "@web/model/relational_model/static_list";

function makeSpyList() {
    return {
        _commands: [],
        _currentIds: [],
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
            __proto__: MODEL_LIFECYCLE_PROTO,
            hooks: {
                lifecycle: {},
                ui: { onDisplayInvalidFields: () => () => {} },
            },
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
            _membership: new ListMembership(),
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
            _cache: markRaw(new Map()),
            _commands: [],
            _initialCommands: [],
            _commandsPromise: null,
            _savePoint: undefined,
            _unknownRecordCommands: new Map(),
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
            list._cache.set(id, {
                resId: id,
                _virtualId: false,
                _discard() {},
                _addSavePoint() {},
            });
        }
        return list;
    }

    test("a slot opened before the savepoint survives the discard", () => {
        const list = makeList();
        list._bumpLimit(1);
        list._currentIds = [1, 2, 3];
        expect(list.limit).toBe(3);

        list._addSavePoint();
        list._bumpLimit(1);
        expect(list.limit).toBe(4);

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

        list._discard();

        expect(list.limit).toBe(2);
        expect(list._tmpIncreaseLimit).toBe(0);
        expect(list._currentIds).toEqual([1, 2]);
    });
});
