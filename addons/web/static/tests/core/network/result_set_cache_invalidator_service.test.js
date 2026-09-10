// @ts-check

import { after, describe, expect, test } from "@odoo/hoot";
import { makeMockEnv } from "@web/../tests/web_test_helpers";
import { RpcEvent } from "@web/core/events";
import { RESULT_SET_REMOVING_METHODS } from "@web/core/network/result_set_cache_invalidator_service";
import { ConnectionLostError, rpc, rpcBus, RPCError } from "@web/core/network/rpc";
import { RPCCache } from "@web/core/network/rpc_cache";

describe.current.tags("headless");

/**
 * @param {string} method
 * @param {string} [model]
 */
function fireResponse(method, model = "res.partner") {
    rpcBus.dispatchEvent(
        new CustomEvent(RpcEvent.RESPONSE, {
            detail: { data: { params: { method, model } }, settings: {} },
        }),
    );
}

function captureClearCaches() {
    /** @type {any[]} */
    const captured = [];
    const listener = (/** @type {Event} */ ev) =>
        captured.push(/** @type {CustomEvent} */ (ev).detail);
    rpcBus.addEventListener(RpcEvent.CLEAR_CACHES, listener);
    return {
        captured,
        stop: () => rpcBus.removeEventListener(RpcEvent.CLEAR_CACHES, listener),
    };
}

test("RESULT_SET_REMOVING_METHODS contract is locked", () => {
    expect(RESULT_SET_REMOVING_METHODS.size).toBe(3);
    expect(RESULT_SET_REMOVING_METHODS.has("unlink")).toBe(true);
    expect(RESULT_SET_REMOVING_METHODS.has("action_archive")).toBe(true);
    expect(RESULT_SET_REMOVING_METHODS.has("action_unarchive")).toBe(true);
});

test("unlink response emits a model-scoped CLEAR-CACHES", async () => {
    await makeMockEnv();
    const { captured, stop } = captureClearCaches();

    fireResponse("unlink", "res.partner");

    expect(captured).toHaveLength(1);
    expect(captured[0].model).toBe("res.partner");
    expect(captured[0].tables).toEqual([
        "web_read",
        "web_search_read",
        "web_read_group",
    ]);

    stop();
});

test("action_archive and action_unarchive both emit", async () => {
    await makeMockEnv();
    const { captured, stop } = captureClearCaches();

    fireResponse("action_archive", "sale.order");
    fireResponse("action_unarchive", "stock.picking");

    expect(captured).toHaveLength(2);
    expect(captured[0].model).toBe("sale.order");
    expect(captured[1].model).toBe("stock.picking");

    stop();
});

test("write-class methods do NOT emit (D3b regression guard)", async () => {
    await makeMockEnv();
    const { captured, stop } = captureClearCaches();

    fireResponse("write");
    fireResponse("web_save");
    fireResponse("web_save_multi");
    fireResponse("create");

    expect(captured).toHaveLength(0);

    stop();
});

test("read-class methods do NOT emit", async () => {
    await makeMockEnv();
    const { captured, stop } = captureClearCaches();

    fireResponse("web_read");
    fireResponse("web_search_read");
    fireResponse("web_read_group");
    fireResponse("name_search");

    expect(captured).toHaveLength(0);

    stop();
});

test("language installation clears every cache only for its own model", async () => {
    await makeMockEnv();
    const { captured, stop } = captureClearCaches();

    fireResponse("action_install_lang", "res.partner");
    fireResponse("write", "base.language.install");
    expect(captured).toHaveLength(0);

    fireResponse("action_install_lang", "base.language.install");
    expect(captured).toEqual([null]);
    stop();
});

test("malformed payloads do not throw", async () => {
    await makeMockEnv();
    const { captured, stop } = captureClearCaches();

    rpcBus.dispatchEvent(new CustomEvent(RpcEvent.RESPONSE, { detail: null }));
    rpcBus.dispatchEvent(
        new CustomEvent(RpcEvent.RESPONSE, { detail: { data: null } }),
    );
    rpcBus.dispatchEvent(
        new CustomEvent(RpcEvent.RESPONSE, {
            detail: { data: { params: null } },
        }),
    );
    rpcBus.dispatchEvent(
        new CustomEvent(RpcEvent.RESPONSE, {
            detail: { data: { params: {} } },
        }),
    );

    expect(captured).toHaveLength(0);

    stop();
});

/**
 * @param {string} method
 * @param {any} error
 * @param {string} [model]
 */
function fireFailedResponse(method, error, model = "res.partner") {
    rpcBus.dispatchEvent(
        new CustomEvent(RpcEvent.RESPONSE, {
            detail: { data: { params: { method, model } }, settings: {}, error },
        }),
    );
}

test("a rejected language installation preserves caches", async () => {
    await makeMockEnv();
    const { captured, stop } = captureClearCaches();

    fireFailedResponse(
        "action_install_lang",
        new RPCError("denied"),
        "base.language.install",
    );
    expect(captured).toHaveLength(0);
    stop();
});

test("a lost language installation response clears every cache", async () => {
    await makeMockEnv();
    const { captured, stop } = captureClearCaches();

    fireFailedResponse(
        "action_install_lang",
        new ConnectionLostError("/web/dataset/call_kw"),
        "base.language.install",
    );
    expect(captured).toEqual([null]);
    stop();
});

test("language installation evicts cached results across tables and models", async () => {
    await makeMockEnv();
    const cache = new RPCCache("language-install-audit", 1);
    rpc.setCache(cache);
    after(() => rpc.setCache(undefined));
    const entries = [
        ["web_read", "res.partner"],
        ["web_search_read", "product.product"],
        ["translations", "ir.ui.view"],
    ];
    let version = "before";
    const readEntries = () =>
        Promise.all(
            entries.map(([table, model]) =>
                cache.read(table, model, () => Promise.resolve(version), { model }),
            ),
        );
    expect(await readEntries()).toEqual(["before", "before", "before"]);
    version = "after";
    fireFailedResponse(
        "action_install_lang",
        new RPCError("denied"),
        "base.language.install",
    );
    expect(await readEntries()).toEqual(["before", "before", "before"]);
    fireResponse("action_install_lang", "base.language.install");
    expect(await readEntries()).toEqual(["after", "after", "after"]);
});

test("a server-rejected unlink does NOT emit", async () => {
    await makeMockEnv();
    const { captured, stop } = captureClearCaches();

    fireFailedResponse("unlink", new RPCError("denied"));

    expect(captured).toHaveLength(0);
    stop();
});

test("an unlink whose response was LOST still emits", async () => {
    await makeMockEnv();
    const { captured, stop } = captureClearCaches();

    fireFailedResponse("unlink", new ConnectionLostError("/web/dataset/call_kw"));

    expect(captured).toHaveLength(1);
    expect(captured[0].model).toBe("res.partner");
    stop();
});

test("a failed write-class method still does NOT emit", async () => {
    await makeMockEnv();
    const { captured, stop } = captureClearCaches();

    fireFailedResponse("web_save", new ConnectionLostError("/web/dataset/call_kw"));

    expect(captured).toHaveLength(0);
    stop();
});
