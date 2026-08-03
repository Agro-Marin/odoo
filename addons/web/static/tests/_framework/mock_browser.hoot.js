// @ts-check

import { afterEach, beforeEach, mockHistory, mockLocation } from "@odoo/hoot";

/**
 * Timer/animation primitives that HOOT already mocks (via its virtual clock:
 * ``advanceTime``/``runAllTimers``). They are exposed as getter-only properties
 * so plain reassignment (``browser.setTimeout = ...``) can't silently swap out
 * HOOT's mock and break time control. They stay ``configurable: true`` — like
 * ``location``/``history`` above — so a test can still install a *delegating*
 * spy through ``patchWithCleanup(browser, { setInterval() { ... super.setInterval() } })``
 * (the standard Odoo pattern); the getter-only shape keeps the anti-footgun
 * guarantee since assignment still throws with no setter.
 */
const READONLY_PROPERTIES = [
    "cancelAnimationFrame",
    "clearInterval",
    "clearTimeout",
    "requestAnimationFrame",
    "setInterval",
    "setTimeout",
];

/**
 * Patch the live ``browser`` singleton so ``browser.location``/``browser.history``
 * read/write HOOT's in-memory ``mockLocation``/``mockHistory`` instead of forwarding
 * to the real ``window.location``/``window.history``.
 *
 * (so ``patchWithCleanup(browser.location, {...})`` in a single test can
 * override individual properties without touching the non-configurable real
 * ``window.location``).
 *
 * Without this, code that calls ``browser.location.assign(...)``,
 * ``browser.history.pushState/replaceState(...)``, or ``history.back/forward/go``
 * triggers a real navigation or URL-bar mutation mid-suite — observed as real
 * ``GET /odoo`` requests, a redirect to the PWA offline fallback, and Hoot
 * stalling for the rest of the 900s timeout. ``mockHistory`` is built against
 * ``mockLocation`` (see ``hoot/mock/network.js``) so pushState/back stay consistent.
 *
 * Production is unaffected — only invoked from the test bundle's ``setupTestEnvironment``.
 */
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

/**
 * Isolate `localStorage`/`sessionStorage` between tests.
 *
 * Without this, `browser.localStorage` IS `window.localStorage` — the real one —
 * so any test that writes a key leaves it for every test that runs afterwards.
 * The warm-server runner (`tooling/hoot/hoot`) reuses one browser across
 * invocations, so it leaks between RUNS too, which is why two `emoji_picker`
 * tests failed or passed depending on what had run before them rather than on
 * anything they did: `emoji_picker.test.js` writes `web.emoji.frequent` and
 * never restores it, and the picker caps its recents, so a store another suite
 * left full silently changed which emojis rendered.
 *
 * **Snapshot and restore the real objects rather than substituting a fake one.**
 * A hand-rolled `Storage` was tried first and is a trap: the real thing is a
 * property bag as well as an API (`store.foo = 1`), it enumerates entries rather
 * than methods, and — the one that bites hardest — it keeps its API on
 * `Storage.prototype`, which is what makes
 * `patchWithCleanup(browser.localStorage, { removeItem() { … super.getItem(k) …
 * } })` resolve. A literal with own-property methods ends that `super` chain at
 * `Object.prototype`. Reproducing all of it faithfully is strictly more work
 * than not replacing the object at all.
 *
 * HOOT keeps its own keys in `localStorage` (see `hoot_utils.js`); restoring the
 * exact prior contents leaves those untouched, where a blanket `clear()` would
 * not.
 */
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
