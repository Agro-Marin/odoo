// @ts-check

import { advanceTime, animationFrame, describe, expect, test } from "@odoo/hoot";
import {
    getService,
    makeMockEnv,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { RpcEvent } from "@web/core/events";
import { rpc, rpcBus } from "@web/core/network/rpc";
import { SLOW_RPC_CONFIG } from "@web/core/network/slow_rpc_service";

describe.current.tags("headless");

/**
 * @param {number} id
 * @param {{silent?: boolean}} [settings]
 */
function fireRequest(id, settings = {}) {
    rpcBus.dispatchEvent(
        new CustomEvent(RpcEvent.REQUEST, {
            detail: { data: { id }, url: "/test", settings },
        }),
    );
}

/** @param {number} id */
function fireResponse(id) {
    rpcBus.dispatchEvent(
        new CustomEvent(RpcEvent.RESPONSE, {
            detail: { data: { id }, settings: {} },
        }),
    );
}

function patchNotification() {
    const notification = getService("notification");
    patchWithCleanup(notification, {
        add(message, opts) {
            expect.step(`add:${message}|sticky=${!!opts?.sticky}`);
            return () => expect.step(`close:${message}`);
        },
    });
}

test("does not notify when RPC completes before threshold", async () => {
    patchWithCleanup(SLOW_RPC_CONFIG, { thresholdMs: 1000 });
    await makeMockEnv();
    patchNotification();

    fireRequest(1);
    await advanceTime(500);
    fireResponse(1);
    await advanceTime(2000);

    expect.verifySteps([]);
});

test("notifies when RPC exceeds threshold", async () => {
    patchWithCleanup(SLOW_RPC_CONFIG, { thresholdMs: 100 });
    await makeMockEnv();
    patchNotification();

    fireRequest(1);
    await advanceTime(150);

    expect.verifySteps(["add:This is taking longer than usual…|sticky=true"]);

    fireResponse(1);
    expect.verifySteps(["close:This is taking longer than usual…"]);
});

test("env teardown closes a toast still open for an in-flight request", async () => {
    patchWithCleanup(SLOW_RPC_CONFIG, { thresholdMs: 100 });
    const env = await makeMockEnv();
    patchNotification();

    fireRequest(1);
    await advanceTime(150);
    expect.verifySteps(["add:This is taking longer than usual…|sticky=true"]);

    env.destroy();
    expect.verifySteps(["close:This is taking longer than usual…"]);
});

test("dismisses notification on response after threshold", async () => {
    patchWithCleanup(SLOW_RPC_CONFIG, { thresholdMs: 100 });
    await makeMockEnv();
    patchNotification();

    fireRequest(1);
    await advanceTime(150);
    fireResponse(1);

    expect.verifySteps([
        "add:This is taking longer than usual…|sticky=true",
        "close:This is taking longer than usual…",
    ]);
});

test("skips silent requests entirely", async () => {
    patchWithCleanup(SLOW_RPC_CONFIG, { thresholdMs: 50 });
    await makeMockEnv();
    patchNotification();

    fireRequest(1, { silent: true });
    await advanceTime(200);
    fireResponse(1);

    expect.verifySteps([]);
});

test("concurrent slow requests share a single toast", async () => {
    patchWithCleanup(SLOW_RPC_CONFIG, { thresholdMs: 100 });
    await makeMockEnv();
    patchNotification();

    fireRequest(1);
    fireRequest(2);
    await advanceTime(150);
    expect.verifySteps(["add:This is taking longer than usual…|sticky=true"]);

    fireResponse(1);
    expect.verifySteps([]);

    fireResponse(2);
    expect.verifySteps(["close:This is taking longer than usual…"]);
});

test("shared toast reopens for a slow request after the first batch settled", async () => {
    patchWithCleanup(SLOW_RPC_CONFIG, { thresholdMs: 100 });
    await makeMockEnv();
    patchNotification();

    fireRequest(1);
    await advanceTime(150);
    fireResponse(1);
    expect.verifySteps([
        "add:This is taking longer than usual…|sticky=true",
        "close:This is taking longer than usual…",
    ]);

    fireRequest(2);
    await advanceTime(150);
    fireResponse(2);
    expect.verifySteps([
        "add:This is taking longer than usual…|sticky=true",
        "close:This is taking longer than usual…",
    ]);
});

test("response without matching request is a no-op", async () => {
    patchWithCleanup(SLOW_RPC_CONFIG, { thresholdMs: 100 });
    await makeMockEnv();
    patchNotification();

    fireResponse(999);
    await advanceTime(200);

    expect.verifySteps([]);
});

test("a real aborted RPC clears its sticky toast", async () => {
    patchWithCleanup(SLOW_RPC_CONFIG, { thresholdMs: 100 });
    await makeMockEnv();
    patchNotification();
    onRpc("/hang", () => new Promise(() => {}));

    const prom = rpc("/hang", {});
    prom.catch(() => {});
    await advanceTime(150);
    expect.verifySteps(["add:This is taking longer than usual…|sticky=true"]);

    prom.abort();
    await animationFrame();
    expect.verifySteps(["close:This is taking longer than usual…"]);
});
