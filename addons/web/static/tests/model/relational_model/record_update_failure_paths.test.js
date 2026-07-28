// @ts-check

/**
 * Regression tests for the three failure paths of ``RelationalRecord._update``
 * and for the validity half of ``_applyChanges``'s undo closure.
 *
 * ``_update`` raises ``dirty`` up-front (Invariant 1) and each of its three
 * catch blocks must lower it again when nothing was committed. The onchange
 * catch used to skip ``restoreDirty()``, so a failed ``onchange`` RPC left a
 * record flagged dirty with an empty change set — a discard prompt and a dirty
 * indicator for edits that were never applied.
 *
 * Separately, ``_applyChanges``'s undo restored ``_invalidFields`` but not
 * ``_unsetRequiredFields``. The two are paired: a later
 * ``_checkValidity({removeInvalidOnly})`` iterates ``_unsetRequiredFields`` to
 * decide what to re-scan, so dropping an entry there leaves the matching
 * ``_invalidFields`` entry unreachable by any prune.
 *
 * Uses the REAL ``RelationalRecord`` (and the real validator) against a mock
 * model; ``record_apply_changes_undo.test.js`` covers the x2many half of the
 * same undo closure with ``_checkValidity`` stubbed out.
 */

import { describe, expect, test } from "@odoo/hoot";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { RelationalRecord } from "@web/model/relational_model/record";
import { RecordEditState } from "@web/model/relational_model/record_edit_state";

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
            hooks: { ui: { onDisplayInvalidFields: () => () => {} } },
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
        // An onchange carrying a properties field expands into extra
        // ``<field>.<name>`` entries; ``_parseServerValues`` is where that
        // expansion lands, so stub it to add one.
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
