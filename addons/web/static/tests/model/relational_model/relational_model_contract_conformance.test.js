// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Mutex } from "@web/core/utils/concurrency";
import { RelationalModel } from "@web/model/relational_model/relational_model";
import { RELATIONAL_MODEL_SURFACE } from "@web/model/relational_model/relational_model_contract";

describe.current.tags("headless");

const isPrototypeMethod = (/** @type {string} */ key) =>
    typeof Object.getOwnPropertyDescriptor(RelationalModel.prototype, key)?.value ===
    "function";
const OPERATIONS = RELATIONAL_MODEL_SURFACE.filter(isPrototypeMethod);
const STATE = RELATIONAL_MODEL_SURFACE.filter((key) => !isPrototypeMethod(key));

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
        const called = [
            "askChanges",
            "fetchExactCount",
            "loadNewRecord",
            "loadRecords",
            "onchange",
            "patchConfig",
            "reloadWithConfig",
            "updateSimilarRecords",
        ];
        const missing = called.filter((key) => !OPERATIONS.includes(key));
        expect(missing).toEqual([], {
            message:
                "RELATIONAL_MODEL_SURFACE names an operation RelationalModel no " +
                "longer has -- update the contract, and every datapoint using it",
        });
    });

    test("every state member the contract names exists on a real model", () => {
        const model = makeRealModel();
        const missing = STATE.filter((key) => !(key in model));
        expect(missing).toEqual([], {
            message:
                "the state half is per-instance, so it is checked against " +
                "a constructed model rather than the prototype",
        });
    });

    test("control: the members really are what the contract claims", () => {
        expect(OPERATIONS.length).toBeGreaterThan(10);
        expect(STATE.length).toBeGreaterThan(5);
        expect(RELATIONAL_MODEL_SURFACE.filter((key) => key.startsWith("_"))).toEqual(
            [],
            {
                message:
                    "a member datapoints reach is public; the underscore was the lie",
            },
        );
        expect(makeRealModel().mutex).toBeInstanceOf(Mutex, {
            message: "`mutex` is the concurrency primitive datapoints serialise on",
        });
    });
});

describe("the contract's declared SHAPES, which a name check cannot see", () => {
    test("reloadWithConfig calls `commit` — it is a function, not a flag", async () => {
        const model = makeRealModel();
        const loaded = { records: [{ id: 1 }], length: 1 };
        /** @type {any[]} */
        const received = [];
        model._loadData = async () => loaded;
        model.patchConfig = (/** @type {any} */ c, /** @type {any} */ p) =>
            Object.assign(c, p);

        await model.reloadWithConfig(
            /** @type {any} */ ({ isRoot: false, activeFields: {}, fields: {} }),
            {},
            { commit: (data) => received.push(data) },
        );

        expect(received).toEqual([loaded], {
            message: "`commit` must be invoked with the loaded data",
        });
    });

    test("loadRecords accepts the cache and signal it declares", async () => {
        const model = makeRealModel();
        /** @type {any[]} */
        const seen = [];
        model.orm = /** @type {any} */ ({
            cache: (/** @type {any} */ c) => {
                seen.push(["cache", c]);
                return model.orm;
            },
            withSignal: (/** @type {any} */ sg) => {
                seen.push(["signal", Boolean(sg)]);
                return model.orm;
            },
            webRead: async () => [{ id: 1 }],
        });
        const controller = new AbortController();
        await model.loadRecords(
            /** @type {any} */ ({
                resModel: "line",
                resId: 1,
                activeFields: { name: { context: "{}", invisible: "False" } },
                fields: { name: { name: "name", type: "char" } },
                context: {},
            }),
            {},
            { type: "disk" },
            controller.signal,
        );

        expect(seen).toEqual([
            ["cache", { type: "disk" }],
            ["signal", true],
        ]);
    });
});
