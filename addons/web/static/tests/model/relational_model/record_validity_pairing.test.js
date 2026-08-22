// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { markRaw } from "@odoo/owl";
import { makeRecordDouble } from "@web/../tests/model/relational_model/record_doubles";
import { RecordEditState } from "@web/model/relational_model/record_edit_state";
import { addSavePoint, discard } from "@web/model/relational_model/record_savepoint";
import { checkValidity } from "@web/model/relational_model/record_validator";

/**
 * @param {Object} [opts]
 * @param {boolean} [opts.isNew]
 * @param {Record<string, any>} [opts.data]
 * @param {(fieldName: string) => boolean} [opts.isRequired]
 */
function makeRecord({ isNew = true, data = {}, isRequired = () => false } = {}) {
    const rec = makeRecordDouble({ isNew, data, values: data, isRequired });
    rec._checkValidity = (/** @type {any} */ options) => checkValidity(rec, options);
    return rec;
}

describe("RecordEditState.clearValidity", () => {
    test("empties both sets", () => {
        const state = new RecordEditState();
        state.invalidFields.add("a");
        state.unsetRequiredFields.add("a");
        state.clearValidity();
        expect([...state.invalidFields]).toEqual([]);
        expect([...state.unsetRequiredFields]).toEqual([]);
    });
});

describe("savepoint", () => {
    test("captures and restores both validity sets", () => {
        const rec = makeRecord({ data: { name: false }, isRequired: () => true });
        rec._checkValidity();
        expect([...rec._invalidFields]).toEqual(["name"]);
        expect([...rec._unsetRequiredFields]).toEqual(["name"]);

        addSavePoint(rec);
        expect(rec._savePoint.unsetRequiredFields).toEqual(["name"]);

        rec.data.name = "filled";
        rec._checkValidity();
        expect([...rec._invalidFields]).toEqual([]);
        expect([...rec._unsetRequiredFields]).toEqual([]);

        rec.data.name = false;
        discard(rec);
        expect([...rec._invalidFields]).toEqual(["name"]);
        expect([...rec._unsetRequiredFields]).toEqual(["name"]);
    });

    test("a restored flag can still be pruned once the field stops being required", () => {
        let required = true;
        const rec = makeRecord({
            data: { name: false },
            isRequired: () => required,
        });
        rec._checkValidity();
        addSavePoint(rec);
        rec.data.name = "filled";
        rec._checkValidity();
        rec.data.name = false;
        discard(rec);

        required = false;
        rec._checkValidity({ removeInvalidOnly: true });

        expect([...rec._invalidFields]).toEqual([]);
        expect([...rec._unsetRequiredFields]).toEqual([]);
    });
});

describe("discard without a savepoint", () => {
    test("clears both sets", () => {
        const rec = makeRecord({
            isNew: true,
            data: { name: false },
            isRequired: () => true,
        });
        rec._checkValidity();
        rec._textValues = markRaw({});
        discard(rec);
        expect([...rec._invalidFields]).toEqual([]);
        expect([...rec._unsetRequiredFields]).toEqual([]);
    });
});
