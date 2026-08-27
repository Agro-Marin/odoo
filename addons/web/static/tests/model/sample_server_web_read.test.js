// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { RelationalModel } from "@web/model/relational_model/relational_model";
import { buildSampleORM } from "@web/model/sample_server";

describe.current.tags("headless");

const FIELDS = {
    id: { name: "id", type: "integer" },
    display_name: { name: "display_name", type: "char" },
    name: { name: "name", type: "char" },
};

/**
 * @param {any[][]} calls
 */
function makeRealOrm(calls) {
    return {
        rpc: (/** @type {any[]} */ ...args) => {
            calls.push(args);
            return Promise.resolve("REAL");
        },
        cache() {
            return Object.assign(Object.create(this), { _cache: true });
        },
        withSignal(/** @type {AbortSignal} */ signal) {
            return Object.assign(Object.create(this), { _signal: signal });
        },
        call(
            /** @type {string} */ model,
            /** @type {string} */ method,
            /** @type {any[]} */ args,
            /** @type {any} */ kwargs,
        ) {
            return this.rpc(`/x/${model}/${method}`, { model, method, args, kwargs });
        },
        webRead(
            /** @type {string} */ model,
            /** @type {number[]} */ ids,
            /** @type {any} */ kwargs,
        ) {
            return this.call(model, "web_read", [ids], kwargs);
        },
    };
}

describe("the sample ORM answers the routes the model actually calls", () => {
    test("web_read returns sample rows for the ids it is given", async () => {
        /** @type {any[][]} */
        const calls = [];
        const orm = buildSampleORM("foo", FIELDS, makeRealOrm(calls));
        const records = await orm.webRead("foo", [1, 3], {
            specification: { name: {} },
        });
        expect(calls).toHaveLength(0);
        expect(records.map((/** @type {any} */ r) => r.id)).toEqual([1, 3]);
        expect(typeof records[0].name).toBe("string");
    });

    test("...through _scopedOrm, which is how the model reaches it", async () => {
        /** @type {any[][]} */
        const calls = [];
        const orm = buildSampleORM("foo", FIELDS, makeRealOrm(calls));
        const scoped = RelationalModel.prototype._scopedOrm.call(
            { orm },
            { type: "disk" },
            new AbortController().signal,
        );
        const records = await scoped.webRead("foo", [2], {
            specification: { name: {} },
        });
        expect(calls).toHaveLength(0);
        expect(records.map((/** @type {any} */ r) => r.id)).toEqual([2]);
    });
});
