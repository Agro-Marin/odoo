// @ts-check

/**
 * `reloadAnalyticPlan` reloads the action context when an analytic plan is
 * written, because views must pick up the field the plan just added. Same
 * `successOnly` reasoning as `stock_warehouse`, and the same total absence of
 * coverage while it hand-rolled the `rpcBus` decode.
 */

import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { makeMockEnv, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { RpcEvent } from "@web/core/events";
import { ConnectionLostError, rpcBus, RPCError } from "@web/core/network";
import { registry } from "@web/core/registry";

describe.current.tags("headless");

/** @type {string[]} */
let actions;

beforeEach(async () => {
    actions = [];
    registry.category("services").add(
        "action",
        {
            start: () => ({
                doAction: (/** @type {string} */ name) => actions.push(name),
            }),
        },
        { force: true },
    );
    await makeMockEnv();
});

/**
 * @param {string} model
 * @param {string} method
 * @param {any} [error]
 */
function fire(model, method, error) {
    rpcBus.trigger(RpcEvent.RESPONSE, {
        data: { params: { model, method } },
        url: "/web/dataset/call_kw",
        settings: { silent: true },
        error,
    });
}

test("a successful analytic-plan write reloads the context", async () => {
    fire("account.analytic.plan", "write");
    await animationFrame();
    expect(actions).toEqual(["reload_context"]);
});

test("a non-mutating method does not reload", async () => {
    fire("account.analytic.plan", "web_search_read");
    await animationFrame();
    expect(actions).toEqual([]);
});

test("another model's write does not reload", async () => {
    fire("account.analytic.line", "write");
    await animationFrame();
    expect(actions).toEqual([]);
});

test("a FAILED write never reloads, whichever way it failed", async () => {
    const rpcError = new RPCError("Access denied");
    rpcError.exceptionName = "odoo.exceptions.AccessError";
    fire("account.analytic.plan", "write", rpcError);
    fire(
        "account.analytic.plan",
        "create",
        new ConnectionLostError("/web/dataset/call_kw"),
    );
    await animationFrame();
    expect(actions).toEqual([]);
});

test("a tour in progress suppresses the reload", async () => {
    patchWithCleanup(browser.localStorage, {
        getItem: (/** @type {string} */ key) =>
            key === "running_tour" ? "some_tour" : null,
    });
    fire("account.analytic.plan", "write");
    await animationFrame();
    expect(actions).toEqual([]);
});
