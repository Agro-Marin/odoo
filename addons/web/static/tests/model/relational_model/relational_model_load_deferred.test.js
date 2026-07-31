// @ts-check

/**
 * ``RelationalModel.load`` hands the SWR cache a callback whose first act is
 * ``await rootLoadDef``. Two loads reach that callback without ever producing a
 * root, and used to leave the deferred pending — parking the callback (and the
 * whole server payload it was handed) for the life of the tab:
 *
 *   - **superseded**: the RPC lands, so ``rpc_cache`` runs the callback, but
 *     ``KeepLast`` drops the result, so the ``await`` inside ``load`` never
 *     returns and the resolve below it is never reached.
 *   - **post-RPC throw**: the RPC lands (callback runs), then ``_loadData``
 *     throws anyway — ``_loadRecords`` raises ``FetchRecordError`` when the
 *     server answers with no row, and ``_postprocessReadGroup`` can throw from
 *     ``_getPropertyDefinition``. NB a *network* failure is NOT this case:
 *     ``rpc_cache``'s ``onRejected`` never invokes subscriber callbacks.
 *
 * Both assert by ticking a bounded number of microtasks and reading a flag, NOT
 * by awaiting the callback: awaiting a parked callback merely hangs, and hoot
 * scores a timed-out test as passed.
 */

import { describe, expect, test } from "@odoo/hoot";
import { Deferred } from "@web/core/utils/concurrency";
import { RelationalModel } from "@web/model/relational_model/relational_model";

/** Let any pending microtask chain drain, without ever blocking on it. */
async function tick(times = 20) {
    for (let i = 0; i < times; i++) {
        await Promise.resolve();
    }
}

/**
 * A RelationalModel with ``_loadData`` under test control and the SWR cache
 * forced on, so ``_getCacheParams`` always hands back a real callback.
 */
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
            // Enough surface for the SWR callback's happy path to run to the
            // end: it reads ``config``, scans ``records`` for dirty rows, then
            // hands the fresh payload to ``_setData``.
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
 * Start the callback the SWR cache would run and report whether it ever
 * returned, without awaiting it.
 *
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

        // The RPC landed, so rpc_cache runs the callback...
        const cb = startCallback(cacheParams[0]);
        // ...and only then does post-processing throw (FetchRecordError &c).
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

        // A second load supersedes the first; KeepLast will never settle the
        // first one's promise, so nothing downstream of its await ever runs.
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
