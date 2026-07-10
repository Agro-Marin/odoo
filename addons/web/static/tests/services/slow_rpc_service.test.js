// @ts-check

import { advanceTime, describe, expect, test } from "@odoo/hoot";
import {
    getService,
    makeMockEnv,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { RpcEvent } from "@web/core/events";
import { rpcBus } from "@web/core/network/rpc";
import { SLOW_RPC_CONFIG } from "@web/services/slow_rpc_service";

describe.current.tags("headless");

/**
 * Manually dispatch the same RPC bus event shape as ``rpc.js`` does,
 * so the service runs end-to-end without a real fetch.
 *
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

/** Patch the notification service to step-assert add/close order without rendering. */
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

test("handles concurrent requests independently", async () => {
    patchWithCleanup(SLOW_RPC_CONFIG, { thresholdMs: 100 });
    await makeMockEnv();
    patchNotification();

    fireRequest(1);
    fireRequest(2);
    await advanceTime(150);
    expect.verifySteps([
        "add:This is taking longer than usual…|sticky=true",
        "add:This is taking longer than usual…|sticky=true",
    ]);

    fireResponse(1);
    expect.verifySteps(["close:This is taking longer than usual…"]);

    fireResponse(2);
    expect.verifySteps(["close:This is taking longer than usual…"]);
});

test("response without matching request is a no-op", async () => {
    patchWithCleanup(SLOW_RPC_CONFIG, { thresholdMs: 100 });
    await makeMockEnv();
    patchNotification();

    // RESPONSE for an id that was never REQUESTed (e.g. retry chain
    // completing after an outer abort).  Must not throw or notify.
    fireResponse(999);
    await advanceTime(200);

    expect.verifySteps([]);
});
