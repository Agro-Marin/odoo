// @ts-check

import { expect, test } from "@odoo/hoot";
import { advanceTime } from "@odoo/hoot-mock";
import { makeMockEnv, onRpc } from "@web/../tests/web_test_helpers";
import { lostConnectionHandler } from "@web/components/errors/error_handlers";
import { UncaughtPromiseError } from "@web/core/errors/error_service";
import { connectionRecoveryService } from "@web/core/network/connection_recovery_service";
import { ConnectionLostError } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";

/** @returns {any} */
function uncaught() {
    const error = /** @type {any} */ (new UncaughtPromiseError("boom"));
    error.unhandledRejectionEvent = { preventDefault: () => {} };
    return error;
}

test("the service registers itself from the bundle, with no importer", async () => {
    // slow_rpc_service and result_set_cache_invalidator_service rely on the same
    // thing; this asserts the mechanism rather than trusting it.
    expect(registry.category("services").contains("connection_recovery")).toBe(true);
});

test("a torn-down recovery service does not poison a later start on the same env", async () => {
    const env = await makeMockEnv();
    /** @type {string[]} */
    const notified = [];
    env.services.notification.add = (/** @type {string} */ message) => {
        notified.push(String(message));
        return () => {};
    };

    // pass 1
    const first = connectionRecoveryService.start(env);
    env.services.connection_recovery = first;
    expect(lostConnectionHandler(env, uncaught(), new ConnectionLostError("/x"))).toBe(
        true,
    );
    expect(notified.length).toBe(1);
    first.destroy();

    // pass 2 on the SAME env. Before the state moved into the service closure
    // this reported the error as handled -- preventDefault called, rejection
    // swallowed -- and told the user nothing, for the rest of the page's life.
    const second = connectionRecoveryService.start(env);
    env.services.connection_recovery = second;
    expect(lostConnectionHandler(env, uncaught(), new ConnectionLostError("/x"))).toBe(
        true,
    );
    expect(notified.length).toBe(2);
    second.destroy();
});

test("recovery announces the connection is back, once", async () => {
    onRpc("/web/webclient/version_info", () => ({}));
    const env = await makeMockEnv();
    /** @type {string[]} */
    const notified = [];
    env.services.notification.add = (/** @type {string} */ message) => {
        notified.push(String(message));
        return () => {
            notified.push("(dismissed)");
        };
    };
    const recovery = connectionRecoveryService.start(env);
    env.services.connection_recovery = recovery;

    lostConnectionHandler(env, uncaught(), new ConnectionLostError("/x"));
    // a second loss while the notification is up must not stack another
    lostConnectionHandler(env, uncaught(), new ConnectionLostError("/x"));
    expect(notified).toEqual(["Connection lost. Trying to reconnect..."]);

    await advanceTime(2100);
    expect(notified).toEqual([
        "Connection lost. Trying to reconnect...",
        "(dismissed)",
        "Connection restored. You are back online.",
    ]);
    recovery.destroy();
});
