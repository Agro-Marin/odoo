// @ts-check

import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { advanceTime, animationFrame } from "@odoo/hoot-mock";
import { makeMockEnv, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { RpcEvent } from "@web/core/events";
import { ConnectionLostError, rpcBus, RPCError } from "@web/core/network";
import { registry } from "@web/core/registry";

describe.current.tags("headless");

const RELOAD_DEBOUNCE_MS = 300;

let actions;

beforeEach(async () => {
    actions = [];
    registry.category("services").add(
        "action",
        {
            start: () => ({
                doAction: (name) => actions.push(name),
            }),
        },
        { force: true },
    );
    await makeMockEnv();
});

function fire(model, method, error) {
    rpcBus.trigger(RpcEvent.RESPONSE, {
        data: { params: { model, method } },
        url: "/web/dataset/call_kw",
        settings: { silent: true },
        error,
    });
}

async function settle() {
    await advanceTime(RELOAD_DEBOUNCE_MS + 1);
    await animationFrame();
}

test("a successful warehouse write reloads the context", async () => {
    fire("stock.warehouse", "write");
    await settle();
    expect(actions).toEqual(["reload_context"]);
});

test("a burst of warehouse writes coalesces into ONE reload", async () => {
    for (let i = 0; i < 5; i++) {
        fire("stock.warehouse", "create");
    }
    await settle();
    expect(actions).toEqual(["reload_context"]);
});

test("a non-mutating method on stock.warehouse does not reload", async () => {
    fire("stock.warehouse", "web_search_read");
    fire("stock.warehouse", "read");
    await settle();
    expect(actions).toEqual([]);
});

test("another model's write does not reload", async () => {
    fire("stock.picking", "write");
    await settle();
    expect(actions).toEqual([]);
});

test("a FAILED write never reloads, whichever way it failed", async () => {
    const rpcError = new RPCError("Access denied");
    rpcError.exceptionName = "odoo.exceptions.AccessError";
    fire("stock.warehouse", "write", rpcError);
    fire("stock.warehouse", "write", new ConnectionLostError("/web/dataset/call_kw"));
    await settle();
    expect(actions).toEqual([]);
});

test("a tour in progress suppresses the reload", async () => {
    patchWithCleanup(browser.localStorage, {
        getItem: (key) => (key === "running_tour" ? "some_tour" : null),
    });
    fire("stock.warehouse", "write");
    await settle();
    expect(actions).toEqual([]);
});
