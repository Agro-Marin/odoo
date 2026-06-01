// @ts-check

// ! WARNING: this module cannot depend on modules not ending with ".hoot" (except libs) !

import { mockHistory, mockLocation } from "@odoo/hoot";

//-----------------------------------------------------------------------------
// Internal
//-----------------------------------------------------------------------------

/**
 * List of properties that should not be mocked on the browser object.
 *
 * This is because they are already handled by HOOT and tampering with them could
 * lead to unexpected behavior.
 */
const READONLY_PROPERTIES = [
    "cancelAnimationFrame",
    "clearInterval",
    "clearTimeout",
    "requestAnimationFrame",
    "setInterval",
    "setTimeout",
];

//-----------------------------------------------------------------------------
// Exports
//-----------------------------------------------------------------------------

/**
 * Patch the live ``browser`` singleton so reads of ``browser.location`` and
 * ``browser.history`` return HOOT's in-memory ``mockLocation`` /
 * ``mockHistory`` instead of forwarding to the real ``window.location`` /
 * ``window.history``.
 *
 * Background: ``@web/core/browser/browser`` exposes ``location`` as a facade
 * that delegates every read/write to ``window.location``, and ``history`` as
 * a *direct* reference to ``window.history``. In production that indirection
 * is desirable (so ``patchWithCleanup(browser.location, {...})`` in a single
 * test can override individual properties without touching the
 * non-configurable real ``window.location``). In the test runner, however,
 * any code that
 *
 * - calls ``browser.location.assign("/odoo")`` or sets ``browser.location.href``
 * - calls ``browser.history.pushState(...)`` / ``replaceState(...)`` (router)
 * - calls ``browser.history.back()`` / ``forward()`` / ``go(n)``
 *
 * triggers either a *real* navigation or a real URL-bar mutation that
 * destroys the test page mid-suite — observable as the entire
 * ``@web/core/router/internal links`` block firing real ``GET /odoo``
 * requests, the runner navigating to ``/odoo/offline`` (PWA fallback), and
 * Hoot stalling for the rest of the outer 900s timeout. Mutating only
 * ``window.history`` (no real navigation) is enough to break the runner
 * because subsequent code paths read ``location.href`` (now stale) or a
 * service worker prefetch loads the new URL.
 *
 * Wiring ``browser.location`` to ``mockLocation`` and ``browser.history`` to
 * ``mockHistory`` keeps both APIs functional in tests — pushState/assign etc.
 * update a single in-memory URL — while leaving the real browser untouched.
 * ``mockHistory`` is constructed against ``mockLocation`` (see
 * ``hoot/mock/network.js``), so the two stay consistent: a ``pushState`` is
 * observable as a fresh ``browser.location.href`` read, and ``history.back``
 * rewinds the mock URL.
 *
 * Production code is unaffected — this function is only invoked from the
 * test bundle's ``setupTestEnvironment``.
 */
export function patchBrowserLocation() {
    const { loader } = /** @type {any} */ (window).odoo;
    const browserModule = loader.modules.get("@web/core/browser/browser");
    if (!browserModule?.browser) {
        return;
    }
    Object.defineProperty(browserModule.browser, "location", {
        get: () => mockLocation,
        set: (value) => (mockLocation.href = value),
        configurable: true,
    });
    Object.defineProperty(browserModule.browser, "history", {
        get: () => mockHistory,
        configurable: true,
    });
    for (const property of READONLY_PROPERTIES) {
        const originalValue = browserModule.browser[property];
        Object.defineProperty(browserModule.browser, property, {
            configurable: false,
            get: () => originalValue,
        });
    }
}
