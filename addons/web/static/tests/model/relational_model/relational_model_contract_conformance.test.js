// @ts-check

/**
 * `relational_model_contract.js` names what a datapoint may ask of its model.
 * Nothing checks a hand-written list against the class it describes, so a rename
 * in `RelationalModel` would leave the contract naming a member that no longer
 * exists — and every datapoint annotated with it would be typechecked against a
 * fiction.
 *
 * Split by half, for the same reason as the static-list suite. The `_` half is
 * operations and lives on the prototype, so it can be checked without an
 * instance. The public half is mostly per-instance state (`mutex`, `orm`,
 * `root`, `hooks`), which the prototype does not carry at all — those need a
 * constructed model, so they are checked against one built the way
 * `record_doubles_conformance` builds a real record.
 */

import { describe, expect, test } from "@odoo/hoot";
import { Mutex } from "@web/core/utils/concurrency";
import { RelationalModel } from "@web/model/relational_model/relational_model";
import { RELATIONAL_MODEL_SURFACE } from "@web/model/relational_model/relational_model_contract";

describe.current.tags("headless");

const PRIVATE = RELATIONAL_MODEL_SURFACE.filter((k) => k.startsWith("_"));
const PUBLIC = RELATIONAL_MODEL_SURFACE.filter((k) => !k.startsWith("_"));

/** A real RelationalModel, built against the smallest possible config. */
function makeRealModel() {
    return new RelationalModel(
        /** @type {any} */ ({ services: {}, bus: { addEventListener() {} } }),
        /** @type {any} */ ({
            config: {
                resModel: "line",
                activeFields: {},
                fields: {},
                isMonoRecord: true,
                context: {},
            },
        }),
        /** @type {any} */ ({ orm: {} }),
    );
}

describe("the RelationalModel contract and the class agree", () => {
    test("every operation the contract names is a method on the class", () => {
        const missing = PRIVATE.filter(
            (key) => typeof RelationalModel.prototype[key] !== "function",
        );
        expect(missing).toEqual([], {
            message:
                "RELATIONAL_MODEL_SURFACE names an operation RelationalModel no " +
                "longer has -- update the contract, and every datapoint using it",
        });
    });

    test("every public member the contract names exists on a real model", () => {
        const model = makeRealModel();
        const missing = PUBLIC.filter((key) => !(key in model));
        expect(missing).toEqual([], {
            message:
                "the public half is per-instance state, so it is checked against " +
                "a constructed model rather than the prototype",
        });
    });

    test("control: the members really are what the contract claims", () => {
        // Without this the two tests above pass on an empty list, and on a
        // model whose members are all undefined.
        expect(PRIVATE.length).toBeGreaterThan(5);
        expect(PUBLIC.length).toBeGreaterThan(10);
        expect(makeRealModel().mutex).toBeInstanceOf(Mutex, {
            message: "`mutex` is the concurrency primitive datapoints serialise on",
        });
    });
});
