// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Deferred } from "@web/core/utils/concurrency";
import { RelationalModel } from "@web/model/relational_model/relational_model";

async function tick(times = 20) {
    for (let i = 0; i < times; i++) {
        await Promise.resolve();
    }
}

function makeModel() {
    /** @type {Deferred[]} */
    const loadDefs = [];
    class TestModel extends RelationalModel {
        _loadData() {
            const def = new Deferred();
            loadDefs.push(def);
            return def;
        }
        _createRoot() {
            return {
                id: "root",
                config: this.config,
                hasData: true,
                records: /** @type {any[]} */ ([]),
                _setData() {},
            };
        }
        /** @returns {any} */
        _createEmptyRoot() {
            return undefined;
        }
    }
    const model = new TestModel(
        /** @type {any} */ ({ config: { cache: true }, services: {} }),
        {
            config: {
                resModel: "res.partner",
                fields: {},
                activeFields: {},
                context: {},
                domain: [],
                groupBy: [],
                orderBy: [],
                isMonoRecord: false,
            },
        },
        /** @type {any} */ ({ orm: { cache: () => ({}) } }),
    );
    Object.defineProperty(model, "withCache", { value: true });
    /** @type {any[]} */
    const cacheParams = [];
    const original = model._getCacheParams.bind(model);
    model._getCacheParams = (config, def) => {
        const params = original(config, def);
        cacheParams.push(params);
        return params;
    };
    return { model, loadDefs, cacheParams };
}

/**
 * @param {any} params
 */
function startCallback(params) {
    const state = { returned: false };
    params.callback({ records: [], length: 0 }, true).then(() => {
        state.returned = true;
    });
    return state;
}

describe("RelationalModel load deferred lifecycle", () => {
    test("a load that throws after its RPC landed releases the SWR callback", async () => {
        const { model, loadDefs, cacheParams } = makeModel();
        const loadProm = model.load().then(
            () => "resolved",
            () => "rejected",
        );
        expect(cacheParams.length).toBe(1);

        const cb = startCallback(cacheParams[0]);
        loadDefs[0].reject(new Error("no such record"));

        expect(await loadProm).toBe("rejected");
        await tick();
        expect(cb.returned).toBe(true);
    });

    test("a superseded load releases its SWR callback", async () => {
        const { model, loadDefs, cacheParams } = makeModel();
        model.load();
        expect(cacheParams.length).toBe(1);

        const cb = startCallback(cacheParams[0]);

        const second = model.load();
        loadDefs[1].resolve({ records: [], length: 0 });
        await second;
        await tick();

        expect(cb.returned).toBe(true);
    });

    test("a live load's callback still receives its root", async () => {
        const { model, loadDefs, cacheParams } = makeModel();
        const loadProm = model.load();
        /** @type {any} */
        let seen;
        cacheParams[0]
            .callback({ records: [], length: 0 }, true)
            .then(() => (seen = model.root));
        loadDefs[0].resolve({ records: [], length: 0 });
        await loadProm;
        await tick();
        expect(seen).toBe(model.root);
    });
});
