// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { RelationalRecord } from "@web/model/relational_model/record";
import { RecordEditState } from "@web/model/relational_model/record_edit_state";

/** @param {any} multiSaveResult */
function makeRecord(multiSaveResult) {
    /** @type {string[]} */
    const calls = [];
    const record = Object.create(RelationalRecord.prototype);
    Object.assign(record, {
        _editState: new RecordEditState(),
        selected: true,
        canSaveOnUpdate: true,
        data: { foo: "before" },
        evalContext: {},
        evalContextWithVirtualIds: {},
        _config: {
            resId: 1,
            context: {},
            activeFields: { foo: {} },
            fields: { foo: { name: "foo", type: "char" } },
        },
        model: {
            multiEdit: true,
            urgentSave: {
                isActive: false,
                awaitUnlessUrgent: (/** @type {any} */ p) => p,
                unlessUrgent: (/** @type {any} */ fn) => fn(),
            },
            mutex: { exec: (/** @type {any} */ fn) => fn() },
            multiEditDispatch: () => {
                calls.push("multiEditDispatch");
                return multiSaveResult;
            },
        },
        _save: () => {
            calls.push("_save");
            return true;
        },
        _onUpdate: async () => {},
    });
    return { record, calls };
}

describe("multi-edit dispatch from update()", () => {
    test("a declined dispatch does not fall through to a single save", async () => {
        const { record, calls } = makeRecord(undefined);

        const result = await record.update({ foo: "after" }, { save: true });

        expect(calls).toEqual(["multiEditDispatch"]);
        expect(result).toBe(undefined);
    });

    test("a declined dispatch leaves no dirty mark over an empty changeset", async () => {
        const { record } = makeRecord(undefined);

        await record.update({ foo: "after" }, { save: true });

        expect(record._editState.isChangeSetEmpty).toBe(true);
        expect(record.dirty).toBe(false);
    });

    test("the multi-edit answer is forwarded verbatim", async () => {
        const accepted = makeRecord(true);
        expect(await accepted.record.update({ foo: "a" }, { save: true })).toBe(true);
        expect(accepted.calls).toEqual(["multiEditDispatch"]);

        const refused = makeRecord(false);
        expect(await refused.record.update({ foo: "a" }, { save: true })).toBe(false);
        expect(refused.calls).toEqual(["multiEditDispatch"]);
    });

    test("an unselected record still takes the ordinary save path", async () => {
        const { record, calls } = makeRecord(undefined);
        record.selected = false;

        await record.update({ foo: "after" }, { save: true });

        expect(calls).toEqual(["_save"]);
    });
});
