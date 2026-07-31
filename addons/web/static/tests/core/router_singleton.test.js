// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { router, routerBus } from "@web/core/browser/router";
import { globalSingleton } from "@web/core/utils/global_singleton";

describe.current.tags("headless");

/**
 * The router keeps a bus, the current route, a pending-push buffer and the
 * ephemeral-history stack. All of it used to be module-level `let`s, so a
 * second evaluation of the module produced a second bus and a second route --
 * half the application listening to one and pushing to the other -- and
 * registered its three window listeners again, handling every `popstate`
 * twice. `rpc`, `registry`, `templates` and `assets` all anchor their state on
 * the global store for exactly this reason.
 */
describe("router state is anchored on the global store", () => {
    test("the exported bus is the one on the store", () => {
        const store = globalSingleton("router", () => ({}));
        expect(/** @type {any} */ (store).bus).toBe(routerBus);
    });

    test("the store holds the route the router reports", () => {
        const store = /** @type {any} */ (globalSingleton("router", () => ({})));
        expect(store.state).toBe(router.current);
    });

    test("the module-scope side effects are marked as done", () => {
        // `startRouter()` and the window listeners run once, behind this flag
        const store = /** @type {any} */ (globalSingleton("router", () => ({})));
        expect(store.started).toBe(true);
    });

    test("the store owns the mutable collections the router exposes", () => {
        const store = /** @type {any} */ (globalSingleton("router", () => ({})));
        const marker = {};
        router.pushEphemeral(marker);
        expect(store.ephemeralStack.at(-1)).toBe(marker);
        router.releaseEphemeral(marker);

        router.addLockedKey("a-locked-key");
        expect(store.lockedKeys.has("a-locked-key")).toBe(true);
        router.hideKeyFromUrl("a-hidden-key");
        expect(store.hiddenKeysFromUrl.has("a-hidden-key")).toBe(true);
    });
});
