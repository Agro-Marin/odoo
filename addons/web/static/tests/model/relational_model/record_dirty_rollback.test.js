// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { RelationalRecord } from "@web/model/relational_model/record";

describe.current.tags("headless");

function makeRecord(data = {}) {
    const model = {
        _patchConfig: (config, patch) => Object.assign(config, patch),
        urgentSave: {
            isActive: false,
            awaitUnlessUrgent: (promise) => promise,
            unlessUrgent: (fn) => fn(),
        },
        multiEdit: false,
        hasOnRecordChangedHook: false,
    };
    const config = {
        resModel: "test.model",
        resId: 1,
        resIds: [1],
        mode: "readonly",
        isMonoRecord: true,
        context: {},
        activeFields: {
            foo: makeActiveField(),
            partner_id: makeActiveField(),
        },
        fields: {
            foo: { type: "char", name: "foo" },
            partner_id: {
                type: "many2one",
                name: "partner_id",
                relation: "res.partner",
            },
        },
    };
    return new RelationalRecord(
        /** @type {any} */ (model),
        config,
        { id: 1, ...data },
        {},
    );
}

describe("dirty rollback", () => {
    test("m2o re-set to its current value leaves the record clean", async () => {
        const record = makeRecord({
            foo: "yop",
            partner_id: { id: 7, display_name: "Partner" },
        });
        expect(record.dirty).toBe(false);

        await record._update({ partner_id: { id: 7, display_name: "Partner" } });

        expect(record.dirty).toBe(false);
        expect(Object.keys(record._changes)).toEqual([]);
    });

    test("a real change after the no-op still marks dirty", async () => {
        const record = makeRecord({
            foo: "yop",
            partner_id: { id: 7, display_name: "Partner" },
        });

        await record._update({ foo: "changed" });

        expect(record.dirty).toBe(true);
        expect(record._changes.foo).toBe("changed");
    });

    test("a failing _onUpdate rolls dirty back on a pristine record", async () => {
        const record = makeRecord({ foo: "yop" });
        record._onUpdate = () => {
            throw new Error("onUpdate boom");
        };

        let thrown = null;
        try {
            await record._update({ foo: "changed" });
        } catch (e) {
            thrown = e;
        }

        expect(thrown).not.toBe(null);
        expect(thrown.message).toBe("onUpdate boom");
        expect(record.data.foo).toBe("yop");
        expect(Object.keys(record._changes)).toEqual([]);
        expect(record.dirty).toBe(false);
    });

    test("a failing _onUpdate keeps dirty when earlier edits exist", async () => {
        const record = makeRecord({ foo: "yop" });
        await record._update({ foo: "first edit" });
        expect(record.dirty).toBe(true);

        record._onUpdate = () => {
            throw new Error("onUpdate boom");
        };
        let thrown = null;
        try {
            await record._update({ foo: "second edit" });
        } catch (e) {
            thrown = e;
        }

        expect(thrown).not.toBe(null);
        expect(record.data.foo).toBe("first edit");
        expect(record._changes.foo).toBe("first edit");
        expect(record.dirty).toBe(true);
    });
});

describe("undo invalid-field restore", () => {
    test("undoChanges restores flags synchronously without side effects", () => {
        const record = makeRecord({ foo: "yop" });
        record._invalidFields.add("foo");
        record.dirty = true;

        const undo = record._applyChanges({ foo: "fixed" }, {}, { undoable: true });
        expect(record.isFieldInvalid("foo")).toBe(false);

        undo();

        expect(record.isFieldInvalid("foo")).toBe(true);
        expect(record.dirty).toBe(true);
        expect(record.data.foo).toBe("yop");
    });
});
