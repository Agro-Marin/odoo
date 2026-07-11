// @ts-check

import { describe, expect, globals, test } from "@odoo/hoot";

describe.current.tags("headless");

// The service worker runs as a classic script (no exports), so its pure
// helpers cannot be imported: fetch the source and evaluate it against a
// stub `self`, then read the helpers back from the test-hook object the
// script exposes (`self.__ODOO_SW_TEST_HOOKS__`).
/**
 * @type {Promise<{
 *  extractSessionInfo: (html: string) => string | null,
 *  isStaleWhileRevalidateURL: (url: URL) => boolean,
 * }> | null}
 */
let hooksPromise = null;
function loadServiceWorkerHooks() {
    hooksPromise ??= (async () => {
        const response = await globals.fetch("/web/static/src/service_worker.js");
        const source = await response.text();
        /** @type {any} */
        const fakeSelf = { addEventListener: () => {} };
        // Shadow `caches`/`fetch` so any accidental top-level storage or
        // network access fails loudly instead of touching the test origin.
        new Function("self", "caches", "fetch", source)(fakeSelf, undefined, undefined);
        expect(fakeSelf.__ODOO_SW_TEST_HOOKS__).not.toBe(undefined);
        return fakeSelf.__ODOO_SW_TEST_HOOKS__;
    })();
    return hooksPromise;
}

const url = (/** @type {string} */ path) => new URL(path, "https://example.com");

describe("extractSessionInfo", () => {
    test("extracts a simple session info object", async () => {
        const { extractSessionInfo } = await loadServiceWorkerHooks();
        const html = `<html><script>odoo.__session_info__ = {"db":"x","uid":7};</script></html>`;
        expect(extractSessionInfo(html)).toBe(`{"db":"x","uid":7}`);
    });

    test("survives a '};'-containing string value", async () => {
        // The old non-greedy regex (/odoo\.__session_info__\s*=\s*({.*?});/s)
        // truncated the capture at the first "};" INSIDE a string value,
        // corrupting both the scrub and the restore of the cached shell.
        const { extractSessionInfo } = await loadServiceWorkerHooks();
        const info = `{"db":"x","user":"a};b","uid":7}`;
        const html = `<script>odoo.__session_info__ = ${info};</script>`;
        expect(extractSessionInfo(html)).toBe(info);
    });

    test("handles escaped quotes and nested objects", async () => {
        const { extractSessionInfo } = await loadServiceWorkerHooks();
        const info = `{"company":"ACME \\"};\\" Inc","ctx":{"lang":"en_US","nested":{"a":"}"}}}`;
        const html = `odoo.__session_info__ = ${info};\nodoo.other = 1;`;
        expect(extractSessionInfo(html)).toBe(info);
    });

    test("returns null when absent or malformed", async () => {
        const { extractSessionInfo } = await loadServiceWorkerHooks();
        expect(extractSessionInfo("<html>no session</html>")).toBe(null);
        expect(extractSessionInfo("odoo.__session_info__ = null;")).toBe(null);
        // Unterminated object: the scan runs off the end.
        expect(extractSessionInfo(`odoo.__session_info__ = {"a":1`)).toBe(null);
    });
});

describe("isStaleWhileRevalidateURL", () => {
    test("translations and asset bundles match on pathname alone", async () => {
        const { isStaleWhileRevalidateURL } = await loadServiceWorkerHooks();
        expect(
            isStaleWhileRevalidateURL(url("/web/webclient/translations/abc123")),
        ).toBe(true);
        expect(
            isStaleWhileRevalidateURL(url("/web/assets/1/web.assets_web.min.js")),
        ).toBe(true);
        expect(isStaleWhileRevalidateURL(url("/web/assets"))).toBe(true);
    });

    test("images require a cache-busting unique= token", async () => {
        const { isStaleWhileRevalidateURL } = await loadServiceWorkerHooks();
        // A bare /web/image URL is mutable server-side and ACL-scoped: it
        // must never be served stale-first.
        expect(
            isStaleWhileRevalidateURL(url("/web/image/res.partner/7/image_128")),
        ).toBe(false);
        expect(
            isStaleWhileRevalidateURL(
                url("/web/image/res.partner/7/image_128?unique=abc123"),
            ),
        ).toBe(true);
        // An empty token is not a cache-buster.
        expect(
            isStaleWhileRevalidateURL(
                url("/web/image/res.partner/7/image_128?unique="),
            ),
        ).toBe(false);
    });

    test("unrelated paths never match", async () => {
        const { isStaleWhileRevalidateURL } = await loadServiceWorkerHooks();
        expect(isStaleWhileRevalidateURL(url("/web/imagefoo/1?unique=x"))).toBe(false);
        expect(isStaleWhileRevalidateURL(url("/web/assetsfoo/1"))).toBe(false);
        expect(isStaleWhileRevalidateURL(url("/odoo/some-action"))).toBe(false);
        expect(isStaleWhileRevalidateURL(url("/web/dataset/call_kw"))).toBe(false);
    });
});
