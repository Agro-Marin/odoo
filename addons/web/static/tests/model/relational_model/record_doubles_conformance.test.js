// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    makeRecordDouble,
    RECORD_CONTRACT_SURFACE,
} from "@web/../tests/model/relational_model/record_doubles";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { RelationalRecord } from "@web/model/relational_model/record";
import { RECORD_OWNER_SURFACE } from "@web/model/relational_model/record_contract";

describe.current.tags("headless");

function makeRealRecord() {
    const model = {
        Class: { Record: RelationalRecord },
        _patchConfig: (/** @type {any} */ config, /** @type {any} */ patch) =>
            Object.assign(config, patch),
    };
    const config = {
        resModel: "line",
        activeFields: { name: makeActiveField() },
        fields: { name: { type: "char", name: "name" } },
        resId: 1,
        resIds: [1],
        isMonoRecord: true,
        mode: "readonly",
        context: {},
    };
    return new RelationalRecord(
        /** @type {any} */ (model),
        /** @type {any} */ (config),
        { id: 1, name: "n" },
        {},
    );
}

const has = (/** @type {any} */ obj, /** @type {any} */ key) => key in obj;

describe("the record contract, the class and the double agree", () => {
    test("a real RelationalRecord carries every member the contract names", () => {
        const record = makeRealRecord();
        const missing = RECORD_CONTRACT_SURFACE.filter((key) => !has(record, key));
        expect(missing).toEqual([], {
            message:
                "RECORD_CONTRACT_SURFACE names something RelationalRecord no " +
                "longer has -- update the list, then the double",
        });
    });

    test("makeRecordDouble carries every member the contract names", () => {
        const double = makeRecordDouble({ values: { name: "n" } });
        const missing = RECORD_CONTRACT_SURFACE.filter((key) => !has(double, key));
        expect(missing).toEqual([], {
            message: "the double has fallen behind the contract",
        });
    });

    test("the double invents nothing the real record lacks", () => {
        const record = makeRealRecord();
        const double = makeRecordDouble({ values: { name: "n" } });
        const invented = Object.keys(double).filter((key) => !has(record, key));
        expect(invented).toEqual([], {
            message: "the double models members RelationalRecord does not have",
        });
    });

    test("the double's _loadedFieldNames answers the question the real one does", () => {
        const record = makeRealRecord();
        const double = makeRecordDouble({ values: { id: 1, name: "n" } });

        expect(/** @type {Set<string>} */ (record._loadedFieldNames)).toBeInstanceOf(
            Set,
        );
        expect(double._loadedFieldNames).toBeInstanceOf(Set);
        expect(/** @type {Set<string>} */ (record._loadedFieldNames).has("name")).toBe(
            true,
        );
        expect(double._loadedFieldNames.has("name")).toBe(true);
    });

    test("a real RelationalRecord carries every member the OWNER surface names", () => {
        const record = makeRealRecord();
        const missing = RECORD_OWNER_SURFACE.filter((key) => !has(record, key));
        expect(missing).toEqual([], {
            message:
                "RECORD_OWNER_SURFACE names something RelationalRecord no " +
                "longer has -- update the list, and every list that calls it",
        });
    });

    test("the two record surfaces stay disjoint", () => {
        const both = RECORD_CONTRACT_SURFACE.filter((key) =>
            RECORD_OWNER_SURFACE.includes(key),
        );
        expect(both).toEqual([], { message: "named by both record surfaces" });
    });
});

describe("the double BEHAVES like the record, not merely looks like it", () => {
    /**
     * @param {any} record
     * @returns {string}
     */
    function stateOf(record) {
        return JSON.stringify({
            data: { name: record.data.name },
            values: { name: record._values.name },
            changes: { ...record._changes },
            textValues: { ...record._textValues },
            initialTextValues: { ...record._initialTextValues },
            dirty: record.dirty,
        });
    }

    /**
     * @param {any} record
     * @returns {string[]}
     */
    function drive(record) {
        const trace = [];
        record._changes.name = "edited";
        record._textValues.name = "edited";
        record.dirty = true;
        record._rebuildData();
        trace.push(`rebuild ${stateOf(record)}`);
        record._commitChanges();
        trace.push(`commit ${stateOf(record)}`);
        record._changes.name = "again";
        record._textValues.name = "again";
        record.dirty = true;
        record._rebuildData();
        record._discardChanges();
        trace.push(`discard ${stateOf(record)}`);
        record._resetValues({ name: "reset" });
        trace.push(`reset ${stateOf(record)}`);
        return trace;
    }

    test("commit / discard / reset move both to the same state", () => {
        const real = drive(makeRealRecord());
        const double = drive(
            makeRecordDouble({
                values: { name: "n" },
                fields: { name: { type: "char", name: "name" } },
            }),
        );
        expect(double).toEqual(real, {
            message:
                "the double's state transitions have drifted from " +
                "RelationalRecord's -- delegate to RecordEditState rather than " +
                "restating what it does",
        });
    });

    test("the double derives text values from its values, as the constructor does", () => {
        const real = makeRealRecord();
        const double = makeRecordDouble({
            values: { name: "n" },
            fields: { name: { type: "char", name: "name" } },
        });
        expect({ ...double._textValues }).toEqual({ ...real._textValues });
        expect({ ...double._initialTextValues }).toEqual({
            ...real._initialTextValues,
        });
    });
});
