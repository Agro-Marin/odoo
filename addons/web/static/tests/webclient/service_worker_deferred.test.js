// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { Deferred } from "@web/core/utils/concurrency";
import {
    registerServiceWorker,
    serviceWorkerService,
} from "@web/webclient/service_worker_service";

async function hasSettled(/** @type {Promise<any>} */ promise) {
    let settled = false;
    promise.then(
        () => (settled = true),
        () => (settled = true),
    );
    for (let i = 0; i < 5; i++) {
        await Promise.resolve();
    }
    return settled;
}

describe("service worker activation settlement", () => {
    test("helper sanity: hasSettled reports a resolved deferred", async () => {
        const resolved = new Deferred();
        resolved.resolve();
        expect(await hasSettled(resolved)).toBe(true);
        expect(await hasSettled(new Deferred())).toBe(false);
    });

    test("registerServiceWorker settles the deferred when SW is unavailable", async () => {
        const deferred = new Deferred();

        await registerServiceWorker(deferred);

        expect(await hasSettled(deferred)).toBe(true);
    });

    test("a consumer awaiting the deferred proceeds instead of hanging", async () => {
        const deferred = new Deferred();
        await registerServiceWorker(deferred);

        let reachedPastAwait = false;
        await deferred.then(() => {
            reachedPastAwait = true;
        });
        expect(reachedPastAwait).toBe(true);
    });

    test("the service exposes a `registrationSettled` promise that settles", async () => {
        const { registrationSettled } = serviceWorkerService.start();
        expect(await hasSettled(registrationSettled)).toBe(true);
    });

    test("the promise is named for what it guarantees, not for activation", async () => {
        const settled = new Deferred();
        await registerServiceWorker(settled);
        expect(await hasSettled(settled)).toBe(true);
        // `stopWatching` joined the surface so `env.destroy()` can stop the
        // update timer and the visibilitychange listener that
        // `watchServiceWorkerUpdates` installs; without it they outlived every
        // test that started this service.
        expect(Object.keys(serviceWorkerService.start())).toEqual([
            "registrationSettled",
            "stopWatching",
        ]);
    });
});

describe("service worker teardown", () => {
    test("destroy() stops the update watcher installed at registration", async () => {
        let stopped = 0;
        const registration = /** @type {any} */ ({
            waiting: null,
            installing: null,
            active: { state: "activated" },
            addEventListener() {},
            removeEventListener() {},
            update: async () => {},
        });
        patchWithCleanup(browser.navigator, {
            serviceWorker: /** @type {any} */ ({
                ready: Promise.resolve(),
                controller: {},
                register: async () => registration,
                addEventListener() {},
                removeEventListener() {},
            }),
        });
        patchWithCleanup(browser, {
            setInterval: () => 1,
            clearInterval: () => stopped++,
        });

        const service = serviceWorkerService.start();
        // `registrationSettled` resolves in a `finally`, before the return value
        // reaches the constructor's `.then`; wait for the disposer itself.
        for (let i = 0; i < 50 && service.stopWatching === null; i++) {
            await Promise.resolve();
        }
        expect(service.stopWatching).not.toBe(null);

        service.destroy();
        expect(stopped).toBe(1);
    });

    test("destroy() before registration answers still stops the late watcher", async () => {
        let stopped = 0;
        const registration = /** @type {any} */ ({
            waiting: null,
            installing: null,
            active: { state: "activated" },
            addEventListener() {},
            removeEventListener() {},
            update: async () => {},
        });
        patchWithCleanup(browser.navigator, {
            serviceWorker: /** @type {any} */ ({
                ready: Promise.resolve(),
                controller: {},
                register: async () => registration,
                addEventListener() {},
                removeEventListener() {},
            }),
        });
        patchWithCleanup(browser, {
            setInterval: () => 1,
            clearInterval: () => stopped++,
        });

        const service = serviceWorkerService.start();
        service.destroy();
        await service.registrationSettled;
        for (let i = 0; i < 5; i++) {
            await Promise.resolve();
        }

        expect(stopped).toBe(1);
    });
});
