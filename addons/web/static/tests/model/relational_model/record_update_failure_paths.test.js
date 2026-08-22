// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { MODEL_LIFECYCLE_PROTO } from "@web/../tests/model/relational_model/model_doubles";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { RelationalRecord } from "@web/model/relational_model/record";
import { RecordEditState } from "@web/model/relational_model/record_edit_state";

describe.current.tags("headless");

/**
 * @param {{ failIn?: "preprocess" | "onchange" | "onUpdate", required?: boolean }} [options]
 */
function makeRecord({ failIn, required = false } = {}) {
    const record = Object.create(RelationalRecord.prototype);
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
            activeFields: { name: makeActiveField() },
            fields: { name: { type: "char", name: "name" } },
        },
        data: { name: required ? false : "old" },
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
        _isRequired: () => required,
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
    return record;
}

describe("RelationalRecord._update failure paths", () => {
    test("a preprocessor failure lowers dirty again", async () => {
        const record = makeRecord({ failIn: "preprocess" });
        await expect(record._update({ name: "new" })).rejects.toThrow();
        expect(record.dirty).toBe(false);
    });

    test("an onchange failure lowers dirty again", async () => {
        const record = makeRecord({ failIn: "onchange" });
        await expect(record._update({ name: "new" })).rejects.toThrow();
        expect(record.dirty).toBe(false);
        expect(Object.keys(record._changes)).toEqual([]);
    });

    test("an _onUpdate failure lowers dirty again", async () => {
        const record = makeRecord({ failIn: "onUpdate" });
        await expect(record._update({ name: "new" })).rejects.toThrow();
        expect(record.dirty).toBe(false);
    });

    test("a successful update leaves the record dirty", async () => {
        const record = makeRecord();
        await record._update({ name: "new" });
        expect(record.dirty).toBe(true);
        expect(record.data.name).toBe("new");
    });
});

describe("RelationalRecord._applyChanges undo — validity sets", () => {
    test("undo restores both _invalidFields and _unsetRequiredFields", () => {
        const record = makeRecord({ required: true });
        record._checkValidity();
        expect([...record._invalidFields]).toEqual(["name"]);
        expect([...record._unsetRequiredFields]).toEqual(["name"]);

        record._applyChanges({ name: "filled" }, {}, { undoable: true })();

        expect(record.data.name).toBe(false);
        expect([...record._invalidFields]).toEqual(["name"]);
        expect([...record._unsetRequiredFields]).toEqual(["name"]);
    });

    test("a later removeInvalidOnly pass can still clear the restored field", () => {
        const record = makeRecord({ required: true });
        record._checkValidity();
        record._applyChanges({ name: "filled" }, {}, { undoable: true })();

        record.data.name = "filled for real";
        record._checkValidity({ removeInvalidOnly: true });

        expect([...record._invalidFields]).toEqual([]);
        expect([...record._unsetRequiredFields]).toEqual([]);
    });
});

describe("RelationalRecord._applyChanges undo — data keys", () => {
    test("undo removes keys the change introduced", () => {
        const record = makeRecord();
        record._parseServerValues = (values) => ({
            ...values,
            "properties.new_one": "invented by the onchange",
        });

        const undo = record._applyChanges({}, { name: "srv" }, { undoable: true });
        expect("properties.new_one" in record.data).toBe(true);

        undo();

        expect("properties.new_one" in record.data).toBe(false);
        expect(record.data.name).toBe("old");
    });
});
