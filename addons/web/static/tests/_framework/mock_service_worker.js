// @ts-check

import { browser } from "@web/core/browser/browser";

import { patchWithCleanup } from "./patch_test_helpers.js";

/**
 * @param {Partial<ServiceWorkerRegistration>} [overrides]
 * @returns {ServiceWorkerRegistration}
 */
export function mockServiceWorkerRegistration(overrides = {}) {
    const registration = Object.assign(new EventTarget(), {
        active: null,
        installing: null,
        waiting: null,
        onupdatefound: null,
        scope: browser.location.origin,
        updateViaCache: /** @type {const} */ ("imports"),
        cookies: {
            getSubscriptions: async () => [],
            subscribe: async () => {},
            unsubscribe: async () => {},
        },
        navigationPreload: {
            enable: async () => {},
            disable: async () => {},
            getState: async () => ({ enabled: false, headerValue: "true" }),
            setHeaderValue: async () => {},
        },
        pushManager: {
            getSubscription: async () => null,
            permissionState: async () => /** @type {const} */ ("prompt"),
            subscribe: async () => {
                throw new Error("No push subscription configured");
            },
        },
        getNotifications: async () => [],
        showNotification: async () => {},
        unregister: async () => true,
        update: async () => registration,
        ...overrides,
    });
    return registration;
}

/**
 * @param {Partial<ServiceWorkerContainer>} [overrides]
 * @returns {ServiceWorkerContainer}
 */
export function mockServiceWorkerContainer(overrides = {}) {
    const registration = mockServiceWorkerRegistration();
    const serviceWorker = Object.assign(new EventTarget(), {
        controller: null,
        oncontrollerchange: null,
        onmessage: null,
        onmessageerror: null,
        register: async () => registration,
        ready: Promise.resolve(registration),
        getRegistration: async () => registration,
        getRegistrations: async () => [registration],
        startMessages() {},
        ...overrides,
    });
    patchWithCleanup(browser.navigator, { serviceWorker });
    return serviceWorker;
}
