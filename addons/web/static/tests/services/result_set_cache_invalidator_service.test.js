// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { makeMockEnv } from "@web/../tests/web_test_helpers";
import { RpcEvent } from "@web/core/events";
import { rpcBus } from "@web/core/network/rpc";
import { RESULT_SET_REMOVING_METHODS } from "@web/services/result_set_cache_invalidator_service";

describe.current.tags("headless");

/**
 * Fire a synthetic RPC:RESPONSE event matching the shape ``rpc.js``
 * dispatches in production, so the service runs end-to-end without a
 * real fetch.
 *
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

/**
 * Subscribe to CLEAR-CACHES emissions for the duration of one test.
 * Returns the captured detail payloads and a teardown that runs on test
 * cleanup automatically via the global hoot tear-down (subscription
 * lifetime ends when the test completes — rpcBus is a singleton, so we
 * remove the listener explicitly to keep tests isolated).
 */
function captureClearCaches() {
    /** @type {any[]} */
    const captured = [];
    const listener = (ev) => captured.push(ev.detail);
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
