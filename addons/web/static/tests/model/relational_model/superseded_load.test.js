// @ts-check

import { expect, test } from "@odoo/hoot";
import { animationFrame, Deferred } from "@odoo/hoot-mock";
import {
    defineModels,
    defineWebModels,
    fields,
    models,
    mountView,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { RelationalModel } from "@web/model/relational_model/relational_model";

class Foo extends models.Model {
    name = fields.Char();
    bar = fields.Boolean();
    _records = [
        { id: 1, name: "a", bar: true },
        { id: 2, name: "b", bar: false },
        { id: 3, name: "c", bar: true },
    ];
}
defineWebModels();
defineModels([Foo]);

/**
 * @returns {Promise<RelationalModel>}
 */
async function mountListAndGetModel() {
    /** @type {RelationalModel[]} */
    const instances = [];
    patchWithCleanup(RelationalModel.prototype, {
        setup(/** @type {any[]} */ ...args) {
            super.setup(...args);
            instances.push(/** @type {any} */ (this));
        },
    });
    await mountView({
        resModel: "foo",
        type: "list",
        arch: `<list><field name="name"/></list>`,
    });
    return /** @type {RelationalModel} */ (instances.at(-1));
}

test("a superseded load settles its caller instead of hanging forever", async () => {
    const hold = new Deferred();
    let calls = 0;
    onRpc("foo", "web_search_read", async () => {
        calls++;
        if (calls === 2) {
            await hold;
        }
    });

    const model = await mountListAndGetModel();
    expect(calls).toBe(1);

    let supersededSettled = "pending";
    const superseded = model
        .load({ domain: [["bar", "=", true]] })
        .then(() => (supersededSettled = "resolved"))
        .catch(() => (supersededSettled = "rejected"));
    await animationFrame();
    expect(calls).toBe(2);

    const winner = model.load({ domain: [["bar", "=", false]] });
    hold.resolve();
    await winner;
    await superseded;
    await animationFrame();

    expect(supersededSettled).toBe("resolved");
});

test("a superseded load cancels the request it abandons", async () => {
    /** @type {AbortSignal[]} */
    const signals = [];
    const hold = new Deferred();
    let calls = 0;

    patchWithCleanup(RelationalModel.prototype, {
        _scopedOrm(/** @type {any} */ cache, /** @type {AbortSignal} */ signal) {
            if (signal) {
                signals.push(signal);
            }
            return super._scopedOrm(cache, signal);
        },
    });

    onRpc("foo", "web_search_read", async () => {
        calls++;
        if (calls === 2) {
            await hold;
        }
    });

    const model = await mountListAndGetModel();
    const superseded = model.load({ domain: [["bar", "=", true]] }).catch(() => {});
    await animationFrame();

    const supersededSignal = /** @type {AbortSignal} */ (signals.at(-1));
    expect(supersededSignal.aborted).toBe(false);

    const winner = model.load({ domain: [["bar", "=", false]] });
    expect(supersededSignal.aborted).toBe(true);

    hold.resolve();
    await winner;
    await superseded;
    await animationFrame();
});

test("the winning load's signal is never aborted", async () => {
    /** @type {AbortSignal[]} */
    const signals = [];
    patchWithCleanup(RelationalModel.prototype, {
        _scopedOrm(/** @type {any} */ cache, /** @type {AbortSignal} */ signal) {
            if (signal) {
                signals.push(signal);
            }
            return super._scopedOrm(cache, signal);
        },
    });

    const model = await mountListAndGetModel();
    await model.load({ domain: [["bar", "=", true]] });
    await animationFrame();

    expect(signals.length > 0).toBe(true);
    expect(/** @type {AbortSignal} */ (signals.at(-1)).aborted).toBe(false);
});
