// @ts-check

/**
 * Pins the rollback of Invariant 1's provisional dirty mark: ``_update``
 * raises ``dirty`` synchronously (race protection), but an update that turns
 * out to be a no-op (m2o re-set to its current value) or fails
 * (``_onUpdate`` throwing) must not leave a pristine record permanently
 * dirty — every ``isDirty()`` gate (pager, breadcrumbs, beforeLeave) would
 * chase changes that don't exist.
 *
 * Also pins the undo path's flag-only invalid-field restore
 * (``_setInvalidFieldFlag``): no multi-edit UI reaction, no mutex re-entry.
 *
 * Uses the REAL RelationalRecord class against a mock model.
 */

import { describe, expect, test } from "@odoo/hoot";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { RelationalRecord } from "@web/model/relational_model/record";

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
    return new RelationalRecord(model, config, { id: 1, ...data }, {});
}

describe("dirty rollback", () => {
    test("m2o re-set to its current value leaves the record clean", async () => {
        const record = makeRecord({
            foo: "yop",
            partner_id: { id: 7, display_name: "Partner" },
        });
        expect(record.dirty).toBe(false);

        await record._update({ partner_id: { id: 7, display_name: "Partner" } });

        // The no-op filter emptied the update: the provisional Invariant-1
        // mark must be rolled back, not persist forever.
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
        // undoChanges restored the value AND the pre-update dirty flag.
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
        // The first (committed) edit still exists: dirty must stay up.
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

        const undo = record._applyChanges({ foo: "fixed" });
        // _applyChanges cleared the changed field's invalid flag...
        expect(record.isFieldInvalid("foo")).toBe(false);

        undo();

        // ...and undo restored it, along with the captured dirty state —
        // synchronously (flag-only variant), no discard/mode-switch.
        expect(record.isFieldInvalid("foo")).toBe(true);
        expect(record.dirty).toBe(true);
        expect(record.data.foo).toBe("yop");
    });
});
