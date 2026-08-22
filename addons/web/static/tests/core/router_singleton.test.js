// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { router, routerBus } from "@web/core/browser/router";
import { globalSingleton } from "@web/core/utils/global_singleton";

describe.current.tags("headless");

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
