// @ts-check

import { describe, expect, onError, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { makeMockEnv, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { ConnectionLostError, RPCError } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { session } from "@web/session";
import { offlineFailToFetchErrorHandler } from "@web/webclient/errors/offline_fail_to_fetch_error_handler";
import { swallowAllVisitorErrors } from "@web/webclient/errors/visitor_error_handler";

/**
 * The last handler in the chain for a public visitor swallows EVERYTHING, so
 * the conditions under which it declines are the only thing standing between a
 * developer and a silent app. Neither handler had any coverage.
 */
describe.current.tags("desktop");

/** @param {Partial<{ isInternalUser: boolean, debug: any, testMode: any }>} opts */
function visitorEnv({ isInternalUser = false, debug = false, testMode = false } = {}) {
    patchWithCleanup(user, { isInternalUser });
    patchWithCleanup(session, { test_mode: testMode });
    return /** @type {any} */ ({ debug });
}

test("a visitor's error is swallowed", () => {
    const env = visitorEnv();
    expect(swallowAllVisitorErrors(env, new Error("x"), new Error("x"))).toBe(true);
});

test("an internal user's error is never swallowed", () => {
    const env = visitorEnv({ isInternalUser: true });
    expect(swallowAllVisitorErrors(env, new Error("x"), new Error("x"))).toBe(
        undefined,
    );
});

test("a page that never said who is looking keeps errors visible", () => {
    // The handler is registered unconditionally, so it is the one that has to
    // decline when `isInternalUser` was never published. Patched directly:
    // `visitorEnv` would read an explicit `undefined` as "use the default".
    const env = visitorEnv();
    patchWithCleanup(user, { isInternalUser: undefined });
    expect(swallowAllVisitorErrors(env, new Error("x"), new Error("x"))).toBe(
        undefined,
    );
});

test("debug mode and test mode both keep errors visible", () => {
    expect(
        swallowAllVisitorErrors(
            visitorEnv({ debug: "1" }),
            new Error("x"),
            new Error("x"),
        ),
    ).toBe(undefined);
    expect(
        swallowAllVisitorErrors(
            visitorEnv({ testMode: true }),
            new Error("x"),
            new Error("x"),
        ),
    ).toBe(undefined);
});

test("a visitor's lost connection is left to the lost-connection handler", () => {
    // Swallowing it at sequence 0 would beat the reconnect notification at
    // sequence 98: an offline visitor would get no feedback at all.
    const env = visitorEnv();
    const lost = new ConnectionLostError("");
    expect(swallowAllVisitorErrors(env, new Error("boom"), lost)).toBe(undefined);
});

test("an RPCError the app has a notification for still reaches the visitor", () => {
    // Otherwise a visitor hitting e.g. a validation error sees nothing at all.
    const env = visitorEnv();
    registry
        .category("error_notifications")
        .add("odoo.exceptions.ValidationError", { message: "invalid" });
    const rpcError = new RPCError("nope");
    rpcError.exceptionName = "odoo.exceptions.ValidationError";
    expect(swallowAllVisitorErrors(env, rpcError, rpcError)).toBe(undefined);
});

test("an RPCError with no notification registered is swallowed", () => {
    const env = visitorEnv();
    const rpcError = new RPCError("nope");
    rpcError.exceptionName = "odoo.exceptions.SomethingInternal";
    expect(swallowAllVisitorErrors(env, rpcError, rpcError)).toBe(true);
});

test("the three fetch failure messages are treated as a lost connection", async () => {
    const messages = [
        "Failed to fetch",
        "Load failed",
        "NetworkError when attempting to fetch resource.",
    ];
    // Each one is claimed AND reported: when `lostConnectionHandler` declines
    // to show anything, the handler still surfaces a ConnectionLostError rather
    // than letting the failure vanish.
    expect.errors(messages.length);
    const env = await makeMockEnv();
    for (const message of messages) {
        expect(
            offlineFailToFetchErrorHandler(
                env,
                new Error(message),
                new TypeError(message),
            ),
        ).toBe(true, { message });
    }
    await animationFrame();
    expect.verifyErrors(
        messages.map(
            (message) =>
                `Connection to "${message}" couldn't be established or was interrupted`,
        ),
    );
});

test("the synthesized ConnectionLostError carries the original failure", async () => {
    expect.errors(1);
    const original = new TypeError("Failed to fetch");
    onError((ev) => {
        const reason = /** @type {PromiseRejectionEvent} */ (ev).reason;
        expect(reason).toBeInstanceOf(ConnectionLostError);
        expect(reason.cause).toBe(original, {
            message: "the original TypeError survives as the cause",
        });
    });
    const env = await makeMockEnv();
    expect(offlineFailToFetchErrorHandler(env, new Error("boom"), original)).toBe(true);
    await animationFrame();
    expect.verifyErrors([
        `Connection to "Failed to fetch" couldn't be established or was interrupted`,
    ]);
});

test("a handled sync fetch failure default-prevents its error event", async () => {
    // Without it, an offline failure claimed here still counted as an
    // unhandled defect and hit the js_error beacon.
    expect.errors(1);
    const env = await makeMockEnv();
    const error = /** @type {any} */ (new Error("boom"));
    error.event = { preventDefault: () => expect.step("prevented") };
    expect(
        offlineFailToFetchErrorHandler(env, error, new TypeError("Failed to fetch")),
    ).toBe(true);
    expect.verifySteps(["prevented"]);
    await animationFrame();
    expect.verifyErrors([
        `Connection to "Failed to fetch" couldn't be established or was interrupted`,
    ]);
});

test("an unrelated TypeError is left to the next handler", async () => {
    const env = await makeMockEnv();
    const original = new TypeError("x.y is not a function");
    expect(offlineFailToFetchErrorHandler(env, new Error("boom"), original)).toBe(
        false,
    );
});

test("a non-TypeError with a matching message is left alone", async () => {
    // The message alone does not make it a transport failure.
    const env = await makeMockEnv();
    const original = new ConnectionLostError("Failed to fetch");
    expect(offlineFailToFetchErrorHandler(env, new Error("boom"), original)).toBe(
        false,
    );
});
