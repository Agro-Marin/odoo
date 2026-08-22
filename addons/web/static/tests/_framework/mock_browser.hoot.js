// @ts-check

import { afterEach, beforeEach, mockHistory, mockLocation } from "@odoo/hoot";

const READONLY_PROPERTIES = [
    "cancelAnimationFrame",
    "clearInterval",
    "clearTimeout",
    "requestAnimationFrame",
    "setInterval",
    "setTimeout",
];

export function patchBrowserLocation() {
    const { loader } = /** @type {any} */ (window).odoo;
    const browserModule = loader.modules.get("@web/core/browser/browser");
    if (!browserModule?.browser) {
        return;
    }
    Object.defineProperty(browserModule.browser, "location", {
        get: () => mockLocation,
        set: (value) => {
            mockLocation.href = value;
        },
        configurable: true,
    });
    Object.defineProperty(browserModule.browser, "history", {
        get: () => mockHistory,
        configurable: true,
    });
    for (const property of READONLY_PROPERTIES) {
        const originalValue = browserModule.browser[property];
        Object.defineProperty(browserModule.browser, property, {
            configurable: true,
            get: () => originalValue,
        });
    }
}

export function patchBrowserStorage() {
    const snapshot = (/** @type {Storage} */ storage) => {
        /** @type {[string, string][]} */
        const entries = [];
        for (let i = 0; i < storage.length; i++) {
            const key = /** @type {string} */ (storage.key(i));
            entries.push([key, /** @type {string} */ (storage.getItem(key))]);
        }
        return entries;
    };
    const restore = (
        /** @type {Storage} */ storage,
        /** @type {[string, string][]} */ entries,
    ) => {
        storage.clear();
        for (const [key, value] of entries) {
            storage.setItem(key, value);
        }
    };

    /** @type {[Storage, [string, string][]][]} */
    let taken = [];
    beforeEach(
        () => {
            const stores = [globalThis.localStorage, globalThis.sessionStorage];
            taken = stores.filter(Boolean).map((s) => [s, snapshot(s)]);
        },
        { global: true },
    );
    afterEach(
        () => {
            for (const [storage, entries] of taken) {
                restore(storage, entries);
            }
            taken = [];
        },
        { global: true },
    );
}
