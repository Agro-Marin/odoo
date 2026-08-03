// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { makeMockEnv } from "@web/../tests/web_test_helpers";
import { RpcEvent } from "@web/core/events";
import { RESULT_SET_REMOVING_METHODS } from "@web/core/network/result_set_cache_invalidator_service";
import { ConnectionLostError, rpcBus, RPCError } from "@web/core/network/rpc";

describe.current.tags("headless");

/**
 * Fire a synthetic RPC:RESPONSE event matching the shape ``rpc.js`` dispatches,
 * so the service runs end-to-end without a real fetch.
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
 * Subscribe to CLEAR-CACHES emissions for one test. Returns the captured
 * payloads and a stop() to unsubscribe — rpcBus is a singleton, so the
 * listener must be removed explicitly to keep tests isolated.
 */
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
 * As {@link fireResponse}, but for a mutation whose RPC failed.
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

test("a server-rejected unlink does NOT emit", async () => {
    // The server raised, so the transaction rolled back and nothing was
    // deleted. Dropping a cache here is pure waste right after the user
    // already got an error dialog.
    await makeMockEnv();
    const { captured, stop } = captureClearCaches();

    fireFailedResponse("unlink", new RPCError("denied"));

    expect(captured).toHaveLength(0);
    stop();
});

test("an unlink whose response was LOST still emits", async () => {
    // A ConnectionLostError/timeout may have committed server-side: only the
    // response was lost. Skipping here (what this service used to do for every
    // failure) leaves the result-set caches serving deleted rows for the rest
    // of the session, with no other trigger.
    await makeMockEnv();
    const { captured, stop } = captureClearCaches();

    fireFailedResponse("unlink", new ConnectionLostError("/web/dataset/call_kw"));

    expect(captured).toHaveLength(1);
    expect(captured[0].model).toBe("res.partner");
    stop();
});

test("a failed write-class method still does NOT emit", async () => {
    // The method filter must keep applying regardless of the error policy.
    await makeMockEnv();
    const { captured, stop } = captureClearCaches();

    fireFailedResponse("web_save", new ConnectionLostError("/web/dataset/call_kw"));

    expect(captured).toHaveLength(0);
    stop();
});
