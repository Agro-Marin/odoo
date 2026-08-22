// @ts-check

import { describe, expect, globals, test } from "@odoo/hoot";

describe.current.tags("headless");

/**
 * @type {Promise<{
 * extractSessionInfo: (html: string) => string | null,
 * isStaleWhileRevalidateURL: (url: URL) => boolean,
 * restoreSessionInfo: (htmlBody: string, info: string) => string,
 * }> | null}
 */
let hooksPromise = null;
function loadServiceWorkerHooks() {
    hooksPromise ??= (async () => {
        const response = await globals.fetch("/web/static/src/service_worker.js");
        const source = await response.text();
        /** @type {any} */
        const fakeSelf = { addEventListener: () => {} };
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
        expect(extractSessionInfo(`odoo.__session_info__ = {"a":1`)).toBe(null);
    });
});

describe("restoreSessionInfo", () => {
    test("splices info back into the placeholder", async () => {
        const { restoreSessionInfo } = await loadServiceWorkerHooks();
        const info = `{"db":"x","uid":7}`;
        const shell = `<script>odoo.__session_info__ = @@@session_info_secret@@@;</script>`;
        expect(restoreSessionInfo(shell, info)).toBe(
            `<script>odoo.__session_info__ = ${info};</script>`,
        );
    });

    test("preserves `$`-substitution sequences in the session info", async () => {
        const { restoreSessionInfo } = await loadServiceWorkerHooks();
        const info = `{"name":"ACME $' $& $$ $\` $1 Corp"}`;
        const shell = `odoo.__session_info__ = @@@session_info_secret@@@;`;
        expect(restoreSessionInfo(shell, info)).toBe(
            `odoo.__session_info__ = ${info};`,
        );
    });
});

describe("isStaleWhileRevalidateURL", () => {
    test("content-hashed asset bundles match", async () => {
        const { isStaleWhileRevalidateURL } = await loadServiceWorkerHooks();
        expect(
            isStaleWhileRevalidateURL(
                url("/web/assets/d3796119d3095207/web.assets_web.min.js"),
            ),
        ).toBe(true);
        expect(
            isStaleWhileRevalidateURL(
                url("/web/assets/esm/d3796119d3095207/web.assets_web.esm.js"),
            ),
        ).toBe(true);
    });

    test("translations are NOT served stale", async () => {
        const { isStaleWhileRevalidateURL } = await loadServiceWorkerHooks();
        expect(isStaleWhileRevalidateURL(url("/web/webclient/translations"))).toBe(
            false,
        );
        expect(
            isStaleWhileRevalidateURL(
                url("/web/webclient/translations?hash=abc123&lang=fr_FR"),
            ),
        ).toBe(false);
        expect(
            isStaleWhileRevalidateURL(url("/web/webclient/translations/abc123")),
        ).toBe(false);
    });

    test("mutable asset URLs (debug/any/%) are NOT served stale", async () => {
        const { isStaleWhileRevalidateURL } = await loadServiceWorkerHooks();
        expect(
            isStaleWhileRevalidateURL(url("/web/assets/debug/web.assets_web.min.js")),
        ).toBe(false);
        expect(
            isStaleWhileRevalidateURL(url("/web/assets/any/web.assets_web.min.js")),
        ).toBe(false);
        expect(
            isStaleWhileRevalidateURL(url("/web/assets/%/web.assets_web.min.js")),
        ).toBe(false);
        expect(isStaleWhileRevalidateURL(url("/web/assets"))).toBe(false);
    });

    test("images require a cache-busting unique= token", async () => {
        const { isStaleWhileRevalidateURL } = await loadServiceWorkerHooks();
        expect(
            isStaleWhileRevalidateURL(url("/web/image/res.partner/7/image_128")),
        ).toBe(false);
        expect(
            isStaleWhileRevalidateURL(
                url("/web/image/res.partner/7/image_128?unique=abc123"),
            ),
        ).toBe(true);
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
