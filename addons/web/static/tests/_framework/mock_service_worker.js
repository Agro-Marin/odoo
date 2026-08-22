// @ts-check

import { browser } from "@web/core/browser/browser";

import { patchWithCleanup } from "./patch_test_helpers.js";

/**
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
 * @param {Record<string, any>} [overrides]
 * @returns {EventTarget & Record<string, any>}
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
