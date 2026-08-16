// @ts-check

import { browser } from "@web/core/browser/browser";

import { patchWithCleanup } from "./patch_test_helpers.js";

/**
 * A ``ServiceWorkerRegistration`` faithful enough for the ``service_worker``
 * service to walk without throwing.
 *
 * ``ServiceWorkerContainer.register()`` resolves **with a registration**. A fake
 * that resolves with ``undefined`` reads as harmless — the caller awaits it and
 * moves on — but ``registerServiceWorker`` hands the result straight to
 * ``watchServiceWorkerUpdates``, which reads ``registration.waiting``. That
 * throws, and the service's own ``catch`` turns it into
 * ``console.error("Service worker registration failed, …")``.
 *
 * Nothing fails: the tests that install such a fake are asserting the worker's
 * ``message`` channel, not its registration, and the ``finally`` still settles
 * ``activated``. So the only trace is an error in the browser log, and the fact
 * that ``watchServiceWorkerUpdates`` never ran for the whole test — the update
 * promotion, the interval and the visibility handler are all downstream of the
 * line that threw.
 *
 * Keeping the shape here rather than inline is the point: three mail suites
 * wrote the same fake independently and all three got it wrong the same way.
 *
 * @param {Partial<ServiceWorkerRegistration>} [overrides]
 */
export function mockServiceWorkerRegistration(overrides = {}) {
    return {
        active: null,
        installing: null,
        waiting: null,
        addEventListener() {},
        update: async () => {},
        ...overrides,
    };
}

/**
 * Install a fake ``navigator.serviceWorker`` that registers cleanly and can be
 * dispatched on, for the tests that drive the worker's ``message`` channel.
 *
 * ``browser.navigator`` *is* the global ``navigator`` (see
 * ``@web/core/browser/browser``), so patching it here is what makes
 * ``browser.navigator.serviceWorker`` resolve to the fake as well.
 *
 * @param {Record<string, any>} [overrides] merged onto the container, e.g. a
 *  ``register`` that rejects, or a ``controller``.
 * @returns {EventTarget & Record<string, any>} the container, to
 *  ``dispatchEvent`` a ``MessageEvent`` on.
 */
export function mockServiceWorkerContainer(overrides = {}) {
    const serviceWorker = Object.assign(new EventTarget(), {
        register: async () => mockServiceWorkerRegistration(),
        ready: Promise.resolve(),
        ...overrides,
    });
    patchWithCleanup(browser.navigator, { serviceWorker });
    return serviceWorker;
}
