// @ts-check

import { describe, expect, test } from "@odoo/hoot";
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
        expect(Object.keys(serviceWorkerService.start())).toEqual([
            "registrationSettled",
        ]);
    });
});
