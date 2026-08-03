// @ts-check

/**
 * The model-layer helpers take a ``RelationalRecord`` and reach into its
 * ``_``-prefixed surface. That surface is a contract declared only by the
 * class, so a hand-rolled double can fall behind it without anything saying
 * so -- and then the double answers questions the real record would not, or
 * throws on ones it would.
 *
 * Both directions have bitten this suite. Adding ``_unsetRequiredFields`` to
 * the savepoint broke thirty tests at once; more recently a fixture's fake
 * datapoint omitted ``_loadedFieldNames``, so ``_getResIdsToLoad`` -- the
 * question "does this row still need a webRead?" -- threw instead of
 * answering, and the fixture only surfaced when production code started
 * asking it on a path that had not asked before.
 *
 * These tests close the loop:
 *
 *  - a REAL ``RelationalRecord`` must carry every member the contract names,
 *    so renaming one in the class fails HERE rather than orphaning the list;
 *  - {@link makeRecordDouble} must carry them too, so the double cannot fall
 *    behind the list;
 *  - the double must not invent members the real record lacks.
 */

import { describe, expect, test } from "@odoo/hoot";
import {
    makeRecordDouble,
    RECORD_CONTRACT_SURFACE,
} from "@web/../tests/model/relational_model/record_doubles";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { RelationalRecord } from "@web/model/relational_model/record";
// From production, not through the doubles' re-export: the doubles forward
// `RECORD_CONTRACT_SURFACE` only, and importing a name they do not forward made
// this whole suite register ZERO tests rather than fail.
import { RECORD_OWNER_SURFACE } from "@web/model/relational_model/record_contract";

describe.current.tags("headless");

/** A real RelationalRecord, built against the smallest possible model. */
function makeRealRecord() {
    const model = {
        Class: { Record: RelationalRecord },
        _patchConfig: (config, patch) => Object.assign(config, patch),
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

/** `in` rather than hasOwnProperty: accessors live on the prototype. */
const has = (obj, key) => key in obj;

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

        // Same shape, same question: which fields did the server actually send?
        expect(record._loadedFieldNames).toBeInstanceOf(Set);
        expect(double._loadedFieldNames).toBeInstanceOf(Set);
        expect(record._loadedFieldNames.has("name")).toBe(true);
        expect(double._loadedFieldNames.has("name")).toBe(true);
    });

    test("a real RelationalRecord carries every member the OWNER surface names", () => {
        // The second audience: what an owning list or model invokes on a record
        // it holds. The double is NOT checked against it — a double stands in
        // for a record when testing the record's own helpers, and no test drives
        // it as a list would, so requiring it here would be requiring a shape
        // nothing uses.
        const record = makeRealRecord();
        const missing = RECORD_OWNER_SURFACE.filter((key) => !has(record, key));
        expect(missing).toEqual([], {
            message:
                "RECORD_OWNER_SURFACE names something RelationalRecord no " +
                "longer has -- update the list, and every list that calls it",
        });
    });

    test("the two record surfaces stay disjoint", () => {
        // They answer different questions: widen the first and a helper
        // extracted from Record sees more of it; widen the second and every
        // list in the tree does. A member in both means the distinction has
        // collapsed.
        const both = RECORD_CONTRACT_SURFACE.filter((key) =>
            RECORD_OWNER_SURFACE.includes(key),
        );
        expect(both).toEqual([], { message: "named by both record surfaces" });
    });
});
