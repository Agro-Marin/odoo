// @ts-check

/**
 * @module tests/views/list/list_view_performance
 *
 * Regression-guard tests for the web list view performance optimisations.
 *
 * - R4: ListAggregatesRow must not re-render when a data cell click only
 *   toggles `editedRecord` on the parent — it has no reactive subscription
 *   to that.
 * - D3/D3b: unlink / action_archive / action_unarchive emit CLEAR-CACHES
 *   with `{ tables, model }` so only the affected model's entries are
 *   evicted (both remove records from the active-domain result set, which
 *   the model can't self-update). write/create/web_save are EXCLUDED — see
 *   `RESULT_SET_REMOVING_METHODS` in `result_set_cache_invalidator_service.js`.
 * - D3c: verifies the FULL CHAIN — `rpcBus.RPC:RESPONSE` →
 *   `result_set_cache_invalidator_service` → `CLEAR-CACHES` → `rpc.js` →
 *   `rpcCache.invalidateByModel` — actually drops the target model's RAM
 *   cache entries while other models' survive (`rpc_cache.test.js` covers
 *   `invalidateByModel` in isolation).
 */

import { after, beforeEach, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { onRendered } from "@odoo/owl";
import {
    contains,
    defineModels,
    fields,
    getMockEnv,
    makeMockEnv,
    models,
    mountView,
    patchWithCleanup,
    webModels,
} from "@web/../tests/web_test_helpers";
import { rpc, rpcBus } from "@web/core/network/rpc";
import { RPCCache } from "@web/core/network/rpc_cache";
import { ListAggregatesRow } from "@web/views/list/list_aggregates_row";
import { ListRecordRow } from "@web/views/list/list_record_row";

class Currency extends models.Model {
    _name = "res.currency";
    name = fields.Char();
    symbol = fields.Char();
    _records = [{ id: 1, name: "USD", symbol: "$" }];
}

class Foo extends models.Model {
    amount = fields.Monetary({ currency_field: "currency_id" });
    currency_id = fields.Many2one({ relation: "res.currency", default: 1 });
    _records = Array.from({ length: 8 }, (_, i) => ({
        id: i + 1,
        amount: (i + 1) * 100,
        currency_id: 1,
    }));
}

const { ResCompany, ResPartner, ResUsers } = webModels;

defineModels([Currency, Foo, ResCompany, ResPartner, ResUsers]);

beforeEach(async () => {
    if (!getMockEnv()) {
        await makeMockEnv();
    }
});

/**
 * Clicking a data cell toggles `editedRecord` on the parent ListRenderer.
 * `ListAggregatesRow` has no reactive subscription to `editedRecord`, so it
 * MUST NOT re-render.
 */
test.tags("desktop");
test.todo("aggregate row does not re-render when entering edit mode (R4)", async () => {
    patchWithCleanup(ListAggregatesRow.prototype, {
        setup() {
            super.setup(...arguments);
            onRendered(() => {
                expect.step("ListAggregatesRow render");
            });
        },
    });

    await mountView({
        resModel: "foo",
        type: "list",
        arch: `<list editable="bottom">
            <field name="amount" sum="Total"/>
        </list>`,
    });

    expect.verifySteps(["ListAggregatesRow render"]);

    await contains(".o_data_row:first-child .o_data_cell").click();
    await animationFrame();

    expect.verifySteps([]);
});

/**
 * Selecting a record changes `record.selected`, which computeAggregates()
 * depends on when rendering "selected records only" sums. The aggregate row
 * MUST re-render in response.
 */
test.tags("desktop");
test("aggregate row re-renders when a record is selected (R4 positive case)", async () => {
    patchWithCleanup(ListAggregatesRow.prototype, {
        setup() {
            super.setup(...arguments);
            onRendered(() => {
                expect.step("ListAggregatesRow render");
            });
        },
    });

    await mountView({
        resModel: "foo",
        type: "list",
        arch: `<list>
            <field name="amount" sum="Total"/>
        </list>`,
    });

    expect.verifySteps(["ListAggregatesRow render"]);

    await contains(".o_data_row:first-child .o_list_record_selector input").click();
    await animationFrame();

    expect.verifySteps(["ListAggregatesRow render"]);
});

/**
 * Rows are components whose props stay referentially stable for unchanged
 * records, so OWL must skip them: toggling ONE record's selection checkbox
 * changes only that record's `selected` atom — exactly one row component may
 * re-render (the header checkbox and footer aggregates row have their own
 * subscriptions and are allowed to update).
 */
test.tags("desktop");
test("toggling one checkbox re-renders only that record's row (R5)", async () => {
    const rowRenders = [];
    patchWithCleanup(ListRecordRow.prototype, {
        setup() {
            super.setup(...arguments);
            onRendered(() => {
                rowRenders.push(this.props.record.resId);
            });
        },
    });

    await mountView({
        resModel: "foo",
        type: "list",
        arch: `<list editable="bottom">
            <field name="amount"/>
        </list>`,
    });

    expect(rowRenders).toHaveLength(8);
    rowRenders.length = 0;

    await contains(".o_data_row:first-child .o_list_record_selector input").click();
    await animationFrame();

    expect(rowRenders).toEqual([1]);

    expect(".o_data_row:first-child").toHaveClass("o_data_row_selected");
});

/**
 * When a record is unlinked, `relational_model.js` must emit CLEAR-CACHES with
 * `{ tables: string[], model: string }` (not just the tables array).
 * This allows `rpc.js` to dispatch to `invalidateByModel` and evict only the
 * affected model's cache entries.
 */
test("unlink emits CLEAR-CACHES with model name in payload (D3)", () => {
    const received = [];
    const handler = (ev) => received.push(ev.detail);
    rpcBus.addEventListener("CLEAR-CACHES", handler);

    try {
        rpcBus.trigger("RPC:RESPONSE", {
            data: {
                params: { method: "unlink", model: "res.partner" },
            },
        });

        expect(received).toHaveLength(1);
        const payload = received[0];
        expect(payload).toEqual({
            tables: ["web_read", "web_search_read", "web_read_group"],
            model: "res.partner",
        });
    } finally {
        rpcBus.removeEventListener("CLEAR-CACHES", handler);
    }
});

/**
 * RPC responses for methods other than the documented result-set-removing
 * set (``unlink`` / ``action_archive`` / ``action_unarchive``) must NOT
 * trigger CLEAR-CACHES.  Broadly invalidating on every write was attempted
 * 2026-05-17 and reverted (see "cache web_search_read (onUpdate called
 * after another load)" in ``list_view.test.js``).  This guard regression-
 * tests every method that the audit considered and rejected.
 */
test("non-removing RPC:RESPONSE does not emit CLEAR-CACHES (D3 guard)", () => {
    const received = [];
    const handler = (ev) => received.push(ev.detail);
    rpcBus.addEventListener("CLEAR-CACHES", handler);

    try {
        for (const method of ["write", "create", "web_save", "web_save_multi"]) {
            rpcBus.trigger("RPC:RESPONSE", {
                data: { params: { method, model: "res.partner" } },
            });
        }
        for (const method of ["web_read", "web_search_read", "name_search"]) {
            rpcBus.trigger("RPC:RESPONSE", {
                data: { params: { method, model: "res.partner" } },
            });
        }

        expect(received).toHaveLength(0);
    } finally {
        rpcBus.removeEventListener("CLEAR-CACHES", handler);
    }
});

/**
 * Archive must invalidate the same tables for the same reason as unlink:
 * the record disappears from the active-domain result set and the model
 * has no way to self-update an entry that no longer matches the implicit
 * ``active = True`` filter.  Tests the positive path.
 */
test("action_archive emits CLEAR-CACHES with model name (D3b)", () => {
    const received = [];
    const handler = (ev) => received.push(ev.detail);
    rpcBus.addEventListener("CLEAR-CACHES", handler);

    try {
        rpcBus.trigger("RPC:RESPONSE", {
            data: {
                params: { method: "action_archive", model: "res.partner" },
            },
        });

        expect(received).toHaveLength(1);
        expect(received[0]).toEqual({
            tables: ["web_read", "web_search_read", "web_read_group"],
            model: "res.partner",
        });
    } finally {
        rpcBus.removeEventListener("CLEAR-CACHES", handler);
    }
});

/**
 * Symmetric coverage: unarchive promotes a record back into the active
 * result set; the cache backing that result set is now incomplete and
 * must be cleared.
 */
test("action_unarchive emits CLEAR-CACHES with model name (D3b)", () => {
    const received = [];
    const handler = (ev) => received.push(ev.detail);
    rpcBus.addEventListener("CLEAR-CACHES", handler);

    try {
        rpcBus.trigger("RPC:RESPONSE", {
            data: {
                params: { method: "action_unarchive", model: "sale.order" },
            },
        });

        expect(received).toHaveLength(1);
        expect(received[0]).toEqual({
            tables: ["web_read", "web_search_read", "web_read_group"],
            model: "sale.order",
        });
    } finally {
        rpcBus.removeEventListener("CLEAR-CACHES", handler);
    }
});

/**
 * Build a JSON cache key matching the real shape that
 * ``rpc.js`` writes (``JSON.stringify({url, params})``).  ``invalidateByModel``
 * parses each key and matches on ``params.model``, so the seeded keys must
 * carry the model in ``params``.
 *
 * @param {string} model
 * @param {string} method
 * @param {any[]} [args]
 * @returns {string}
 */
function makeCacheKey(model, method, args = []) {
    return JSON.stringify({
        url: `/web/dataset/call_kw/${model}/${method}`,
        params: { model, method, args },
    });
}

/**
 * Install a fresh ``RPCCache`` as the singleton consumer of ``CLEAR-CACHES``
 * events on ``rpcBus``, with cleanup that restores ``null`` after the test.
 * The third constructor arg is the registry-hash secret the cache uses to
 * key its IndexedDB store — value content is irrelevant for RAM-only
 * assertions but must be a syntactically valid hex string.
 *
 * @returns {RPCCache}
 */
function installFreshRpcCache() {
    const cache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    rpc.setCache(cache);
    after(() => rpc.setCache(null));
    return cache;
}

/**
 * Seed the RAM cache with one ``web_search_read`` entry per model so we can
 * verify that the target-model entry is removed while the unrelated-model
 * entry survives.  Seeding via ``ramCache.write`` skips the encrypted
 * IndexedDB write path — the integration we want to test lives entirely
 * in the RAM layer and the bus wiring, not in the disk path that is
 * already covered by ``rpc_cache.test.js``.
 *
 * @param {RPCCache} cache
 * @returns {{ partnerKey: string, userKey: string }}
 */
function seedTwoModels(cache) {
    const partnerKey = makeCacheKey("res.partner", "web_search_read", [[]]);
    const userKey = makeCacheKey("res.users", "web_search_read", [[]]);
    cache.ramCache.write(
        "web_search_read",
        partnerKey,
        { records: [{ id: 1 }] },
        "res.partner",
    );
    cache.ramCache.write(
        "web_search_read",
        userKey,
        { records: [{ id: 7 }] },
        "res.users",
    );
    return { partnerKey, userKey };
}

test("end-to-end: unlink invalidates RAM cache for target model only (D3c)", () => {
    const cache = installFreshRpcCache();
    const { partnerKey, userKey } = seedTwoModels(cache);

    expect(Object.keys(cache.ramCache.ram.web_search_read)).toEqual([
        partnerKey,
        userKey,
    ]);

    rpcBus.trigger("RPC:RESPONSE", {
        data: {
            params: { method: "unlink", model: "res.partner" },
        },
    });

    expect(Object.keys(cache.ramCache.ram.web_search_read)).toEqual([userKey]);
});

test("end-to-end: action_archive invalidates RAM cache for target model only (D3c)", () => {
    const cache = installFreshRpcCache();
    const { partnerKey, userKey } = seedTwoModels(cache);

    rpcBus.trigger("RPC:RESPONSE", {
        data: {
            params: { method: "action_archive", model: "res.partner" },
        },
    });

    expect(Object.keys(cache.ramCache.ram.web_search_read)).toEqual([userKey]);
    void partnerKey;
});

test("end-to-end: action_unarchive invalidates RAM cache for target model only (D3c)", () => {
    const cache = installFreshRpcCache();
    const { partnerKey, userKey } = seedTwoModels(cache);

    rpcBus.trigger("RPC:RESPONSE", {
        data: {
            params: { method: "action_unarchive", model: "res.partner" },
        },
    });

    expect(Object.keys(cache.ramCache.ram.web_search_read)).toEqual([userKey]);
    void partnerKey;
});

/**
 * End-to-end negative: ``write`` must NOT clear the cache.  This is the
 * integration-level counterpart to the D3 guard (which asserts no event
 * is emitted).  If either layer were misconfigured — listener accidentally
 * extended OR the rpc.js consumer accidentally re-routing — this test
 * would catch the regression because the RAM entry would disappear.
 */
test("end-to-end: write does NOT invalidate RAM cache (D3c negative)", () => {
    const cache = installFreshRpcCache();
    const { partnerKey, userKey } = seedTwoModels(cache);

    rpcBus.trigger("RPC:RESPONSE", {
        data: {
            params: { method: "write", model: "res.partner" },
        },
    });

    expect(Object.keys(cache.ramCache.ram.web_search_read)).toEqual([
        partnerKey,
        userKey,
    ]);
});
