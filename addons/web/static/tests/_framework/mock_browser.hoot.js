// @ts-check

// ! WARNING: this module cannot depend on modules not ending with ".hoot" (except libs) !

import { mockHistory, mockLocation } from "@odoo/hoot";

//-----------------------------------------------------------------------------
// Internal
//-----------------------------------------------------------------------------

/** Not mocked: already handled by HOOT, tampering could cause unexpected behavior. */
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
            configurable: false,
            get: () => originalValue,
        });
    }
}
