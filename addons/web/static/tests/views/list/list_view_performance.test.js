// @ts-check

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
