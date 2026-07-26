// @ts-check

/**
 * The ``service_worker`` service's ``activated`` promise must settle on EVERY
 * exit path of ``registerServiceWorker``.
 *
 * It is not a private detail: mail's ``_doSubscribePush`` /
 * ``_doUnsubscribePush`` both ``await`` it *inside* a ``Mutex``
 * (``mail/static/src/webclient/web/webclient.js``), so a promise left pending
 * wedges that mutex for the rest of the session -- every later push
 * (un)subscription queues behind a slot that never frees.
 *
 * The regression guarded here is the no-service-worker exit, which is a real
 * browser state (verified in Chromium: on a plain-HTTP non-loopback origin
 * ``navigator.serviceWorker`` is undefined while ``Notification`` and
 * ``navigator.permissions`` still exist, so mail's permission-change handler
 * does reach the push path). It is also what Hoot mocks
 * (``lib/hoot/mock/navigator.js`` pins it to ``undefined``), so it is the state
 * of every WebClient mounted in this suite.
 *
 * The two other former hangs -- ``register()`` rejecting, and
 * ``serviceWorker.ready`` never resolving -- are covered by the same
 * ``finally`` / bounded race but are not exercised here: stubbing
 * ``navigator.serviceWorker`` fights Hoot's own navigator mock.
 */

import { describe, expect, test } from "@odoo/hoot";
import { Deferred } from "@web/core/utils/concurrency";
import {
    registerServiceWorker,
    serviceWorkerService,
} from "@web/webclient/service_worker_service";

/**
 * True iff `promise` has settled after a few microtask turns.
 *
 * Bare microtasks rather than `animationFrame()`: settlement here is purely
 * synchronous (`deferred.resolve()`), and the mock-clock frame helper does not
 * resolve in a test with no pending timers.
 */
async function hasSettled(promise) {
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
        // Guards the assertion below from passing for the wrong reason.
        const resolved = new Deferred();
        resolved.resolve();
        expect(await hasSettled(resolved)).toBe(true);
        expect(await hasSettled(new Deferred())).toBe(false);
    });

    test("registerServiceWorker settles the deferred when SW is unavailable", async () => {
        // Real product function, real Deferred. `navigator.serviceWorker` is
        // undefined here (Hoot's mock), i.e. the non-secure-context case.
        const deferred = new Deferred();

        await registerServiceWorker(deferred);

        // Was the regression: the function returned without settling, so every
        // `await` on the deferred was permanent and mail's push mutex wedged.
        expect(await hasSettled(deferred)).toBe(true);
    });

    test("a consumer awaiting the deferred proceeds instead of hanging", async () => {
        // Models mail's `_doUnsubscribePush`, which awaits the promise inside
        // a Mutex: what matters is that the await returns at all.
        const deferred = new Deferred();
        await registerServiceWorker(deferred);

        let reachedPastAwait = false;
        await deferred.then(() => {
            reachedPastAwait = true;
        });
        expect(reachedPastAwait).toBe(true);
    });

    test("the service exposes an `activated` promise that settles", async () => {
        // The contract mail now depends on, exercised through the service's
        // own start() rather than the bare function.
        const { activated } = serviceWorkerService.start();
        expect(await hasSettled(activated)).toBe(true);
    });
});
