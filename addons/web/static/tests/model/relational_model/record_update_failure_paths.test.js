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
        setEvalContext() {},
        parseServerValues: (values) => ({ ...values }),
        _getTextValues: () => ({}),
        isFieldInvisible: () => false,
        isFieldRequired: () => required,
        isFieldReadonly: () => false,
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

describe("RelationalRecord.updateLocked failure paths", () => {
    test("a preprocessor failure lowers dirty again", async () => {
        const record = makeRecord({ failIn: "preprocess" });
        await expect(record.updateLocked({ name: "new" })).rejects.toThrow();
        expect(record.dirty).toBe(false);
    });

    test("an onchange failure lowers dirty again", async () => {
        const record = makeRecord({ failIn: "onchange" });
        await expect(record.updateLocked({ name: "new" })).rejects.toThrow();
        expect(record.dirty).toBe(false);
        expect(Object.keys(record.changes)).toEqual([]);
    });

    test("an _onUpdate failure lowers dirty again", async () => {
        const record = makeRecord({ failIn: "onUpdate" });
        await expect(record.updateLocked({ name: "new" })).rejects.toThrow();
        expect(record.dirty).toBe(false);
    });

    test("a successful update leaves the record dirty", async () => {
        const record = makeRecord();
        await record.updateLocked({ name: "new" });
        expect(record.dirty).toBe(true);
        expect(record.data.name).toBe("new");
    });
});

describe("RelationalRecord.applyChanges undo — validity sets", () => {
    test("undo restores both invalidFields and unsetRequiredFields", () => {
        const record = makeRecord({ required: true });
        record.checkValidityLocked();
        expect([...record.invalidFields]).toEqual(["name"]);
        expect([...record.unsetRequiredFields]).toEqual(["name"]);

        record.applyChanges({ name: "filled" }, {}, { undoable: true })();

        expect(record.data.name).toBe(false);
        expect([...record.invalidFields]).toEqual(["name"]);
        expect([...record.unsetRequiredFields]).toEqual(["name"]);
    });

    test("a later removeInvalidOnly pass can still clear the restored field", () => {
        const record = makeRecord({ required: true });
        record.checkValidityLocked();
        record.applyChanges({ name: "filled" }, {}, { undoable: true })();

        record.data.name = "filled for real";
        record.checkValidityLocked({ removeInvalidOnly: true });

        expect([...record.invalidFields]).toEqual([]);
        expect([...record.unsetRequiredFields]).toEqual([]);
    });
});

describe("RelationalRecord.applyChanges undo — data keys", () => {
    test("undo removes keys the change introduced", () => {
        const record = makeRecord();
        record.parseServerValues = (values) => ({
            ...values,
            "properties.new_one": "invented by the onchange",
        });

        const undo = record.applyChanges({}, { name: "srv" }, { undoable: true });
        expect("properties.new_one" in record.data).toBe(true);

        undo();

        expect("properties.new_one" in record.data).toBe(false);
        expect(record.data.name).toBe("old");
    });
});
