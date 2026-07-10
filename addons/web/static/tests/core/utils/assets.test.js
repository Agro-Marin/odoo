// @ts-check

import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { animationFrame, manuallyDispatchProgrammaticEvent } from "@odoo/hoot-dom";
import { mockFetch } from "@odoo/hoot-mock";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import {
    assetCacheByDocument,
    assets,
    AssetsLoadingError,
    globalBundleCache,
    loadBundle,
    loadCSS,
    loadJS,
} from "@web/core/assets";

describe.current.tags("headless");

/**
 * @param {(node: Node) => void} callback
 */
const mockHeadAppendChild = (callback) => {
    patchWithCleanup(document.head, {
        appendChild: callback,
    });
};

const bundles = {
    "/web/bundle/test.bundle": [
        { type: "link", src: "file1.css" },
        { type: "link", src: "file2.css" },
        { type: "script", src: "file1.js" },
        { type: "script", src: "file2.js" },
    ],
};

beforeEach(() => {
    globalBundleCache.clear();
    assetCacheByDocument.delete(document);
});

test("loadJS: load invalid JS lib", async () => {
    expect.assertions(4);

    mockHeadAppendChild((node) => {
        expect(node).toBeInstanceOf(HTMLScriptElement);
        expect(node).toHaveAttribute("type", "text/javascript");
        expect(node).toHaveAttribute("src", "/some/invalid/file.js");

        // Simulates a failed request to an invalid file.
        manuallyDispatchProgrammaticEvent(node, "error");
    });

    await expect(loadJS("/some/invalid/file.js")).rejects.toThrow(
        /The loading of \/some\/invalid\/file.js failed/,
        { message: "Trying to load an invalid file rejects the promise" },
    );
});

test("loadCSS: load invalid CSS lib", async () => {
    expect.assertions(4 * 4 + 1);

    assets.retries = { count: 3, delay: 1, extraDelay: 1 }; // Fail fast.

    mockHeadAppendChild((node) => {
        expect(node).toBeInstanceOf(HTMLLinkElement);
        expect(node).toHaveAttribute("rel", "stylesheet");
        expect(node).toHaveAttribute("type", "text/css");
        expect(node).toHaveAttribute("href", "/some/invalid/file.css");

        // Simulates a failed request to an invalid file.
        manuallyDispatchProgrammaticEvent(node, "error");
    });

    await expect(loadCSS("/some/invalid/file.css")).rejects.toThrow(
        /The loading of \/some\/invalid\/file.css failed/,
        { message: "Trying to load an invalid file rejects the promise" },
    );
});

test("loadCSS: concurrent loads of the same url share one link + retry chain", async () => {
    // Fail every attempt so the chain exhausts its retries; a short delay keeps
    // the test fast while still exercising the backoff window that used to let
    // a concurrent caller start an independent parallel load+retry chain.
    patchWithCleanup(assets, {
        retries: { count: 3, delay: 1, extraDelay: 1 },
    });
    let appended = 0;
    mockHeadAppendChild((node) => {
        appended++;
        // Simulate a failed request on each injected <link>.
        manuallyDispatchProgrammaticEvent(node, "error");
    });

    const first = loadCSS("/dedupe/file.css");
    // The first attempt has already errored and scheduled its retry (the buggy
    // version deleted the cache entry at this point, so this second call would
    // miss the cache and fork a second chain).
    const second = loadCSS("/dedupe/file.css");
    expect(second).toBe(first);

    await expect(first).rejects.toThrow(/The loading of \/dedupe\/file.css failed/);
    // A single chain = initial attempt + 3 retries = 4 links, not 8.
    expect(appended).toBe(4);
});

test("loadBundle: load js and css files", async () => {
    mockFetch((route) => {
        expect.step(`fetch bundle: ${route.pathname}`);
        return bundles[route.pathname];
    });

    mockHeadAppendChild(async (node) => {
        const srcAttribute = node.tagName === "LINK" ? "href" : "src";
        expect.step(
            `add ${node.tagName} - ${node.type} - ${node.getAttribute(srcAttribute)}`,
        );
    });

    loadBundle("test.bundle");
    await animationFrame();
    expect.verifySteps([
        "fetch bundle: /web/bundle/test.bundle",
        "add LINK - text/css - file1.css",
        "add LINK - text/css - file2.css",
        "add SCRIPT - text/javascript - file1.js",
        "add SCRIPT - text/javascript - file2.js",
    ]);
});

test("loadBundle: load only js files", async () => {
    mockFetch((route) => {
        expect.step(`fetch bundle: ${route.pathname}`);
        return bundles[route.pathname];
    });

    mockHeadAppendChild(async (node) => {
        const srcAttribute = node.tagName === "LINK" ? "href" : "src";
        expect.step(
            `add ${node.tagName} - ${node.type} - ${node.getAttribute(srcAttribute)}`,
        );
    });

    loadBundle("test.bundle", { css: false });
    await animationFrame();
    expect.verifySteps([
        "fetch bundle: /web/bundle/test.bundle",
        "add SCRIPT - text/javascript - file1.js",
        "add SCRIPT - text/javascript - file2.js",
    ]);
});

test("loadBundle: load only css files", async () => {
    mockFetch((route) => {
        expect.step(`fetch bundle: ${route.pathname}`);
        return bundles[route.pathname];
    });

    mockHeadAppendChild(async (node) => {
        const srcAttribute = node.tagName === "LINK" ? "href" : "src";
        expect.step(
            `add ${node.tagName} - ${node.type} - ${node.getAttribute(srcAttribute)}`,
        );
    });

    loadBundle("test.bundle", { js: false });
    await animationFrame();
    expect.verifySteps([
        "fetch bundle: /web/bundle/test.bundle",
        "add LINK - text/css - file1.css",
        "add LINK - text/css - file2.css",
    ]);
});

test("loadBundle: load same bundle in main document and an iframe", async () => {
    mockFetch((route) => {
        expect.step(`fetch bundle: ${route.pathname}`);
        return bundles[route.pathname];
    });

    mockHeadAppendChild(async (node) => {
        const srcAttribute = node.tagName === "LINK" ? "href" : "src";
        expect.step(
            `add document ${node.tagName} - ${node.type} - ${node.getAttribute(srcAttribute)}`,
        );
    });

    const iframe = document.createElement("iframe");
    document.body.appendChild(iframe);
    const iframeDocument = iframe.contentDocument;
    patchWithCleanup(iframeDocument.head, {
        appendChild: (node) => {
            const srcAttribute = node.tagName === "LINK" ? "href" : "src";
            expect.step(
                `add iframe document ${node.tagName} - ${node.type} - ${node.getAttribute(
                    srcAttribute,
                )}`,
            );
        },
    });

    loadBundle("test.bundle");
    await animationFrame();
    expect.verifySteps([
        "fetch bundle: /web/bundle/test.bundle",
        "add document LINK - text/css - file1.css",
        "add document LINK - text/css - file2.css",
        "add document SCRIPT - text/javascript - file1.js",
        "add document SCRIPT - text/javascript - file2.js",
    ]);

    loadBundle("test.bundle", { targetDoc: iframeDocument });
    await animationFrame();
    expect.verifySteps([
        // no fetching as the bundle is cached globally
        "add iframe document LINK - text/css - file1.css",
        "add iframe document LINK - text/css - file2.css",
        "add iframe document SCRIPT - text/javascript - file1.js",
        "add iframe document SCRIPT - text/javascript - file2.js",
    ]);

    iframe.remove();
});

test("loadBundle: load same bundles in 2 iframes", async () => {
    mockFetch((route) => {
        expect.step(`fetch bundle: ${route.pathname}`);
        return bundles[route.pathname];
    });

    mockHeadAppendChild(async (node) => {
        const srcAttribute = node.tagName === "LINK" ? "href" : "src";
        expect.step(
            `add document ${node.tagName} - ${node.type} - ${node.getAttribute(srcAttribute)}`,
        );
    });

    const iframeFirst = document.createElement("iframe");
    const iframeSecond = document.createElement("iframe");
    document.body.appendChild(iframeFirst);
    document.body.appendChild(iframeSecond);
    const iframeDocumentFirst = iframeFirst.contentDocument;
    const iframeDocumentSecond = iframeSecond.contentDocument;
    patchWithCleanup(iframeDocumentFirst.head, {
        appendChild: (node) => {
            const srcAttribute = node.tagName === "LINK" ? "href" : "src";
            expect.step(
                `add iframe document ${node.tagName} - ${node.type} - ${node.getAttribute(
                    srcAttribute,
                )}`,
            );
        },
    });
    patchWithCleanup(iframeDocumentSecond.head, {
        appendChild: (node) => {
            const srcAttribute = node.tagName === "LINK" ? "href" : "src";
            expect.step(
                `add iframe document ${node.tagName} - ${node.type} - ${node.getAttribute(
                    srcAttribute,
                )}`,
            );
        },
    });

    loadBundle("test.bundle", { targetDoc: iframeDocumentFirst });
    await animationFrame();
    expect.verifySteps([
        "fetch bundle: /web/bundle/test.bundle",
        "add iframe document LINK - text/css - file1.css",
        "add iframe document LINK - text/css - file2.css",
        "add iframe document SCRIPT - text/javascript - file1.js",
        "add iframe document SCRIPT - text/javascript - file2.js",
    ]);

    loadBundle("test.bundle", { targetDoc: iframeDocumentSecond });
    await animationFrame();
    expect.verifySteps([
        "add iframe document LINK - text/css - file1.css",
        "add iframe document LINK - text/css - file2.css",
        "add iframe document SCRIPT - text/javascript - file1.js",
        "add iframe document SCRIPT - text/javascript - file2.js",
    ]);

    iframeFirst.remove();
    iframeSecond.remove();
});

test("getBundle: non-ok JSON response rejects and is not cached", async () => {
    let failRequests = true;
    mockFetch((route) => {
        expect.step(`fetch bundle: ${route.pathname}`);
        if (failRequests) {
            // Gateway/proxy error document: non-2xx status with a JSON body.
            return new Response(JSON.stringify({ error: "Bad Gateway" }), {
                status: 502,
                headers: { "Content-Type": "application/json" },
            });
        }
        return bundles[route.pathname];
    });

    await expect(assets.getBundle("test.bundle")).rejects.toThrow(AssetsLoadingError);

    // The failed promise must have been evicted from the cache: the next call
    // re-fetches (and succeeds) instead of returning a poisoned empty bundle.
    failRequests = false;
    const bundle = await assets.getBundle("test.bundle");
    expect(bundle.cssLibs).toEqual(["file1.css", "file2.css"]);
    expect(bundle.jsLibs).toEqual(["file1.js", "file2.js"]);
    expect.verifySteps([
        "fetch bundle: /web/bundle/test.bundle",
        "fetch bundle: /web/bundle/test.bundle",
    ]);
});

test("getBundle: successful response is cached (single fetch for two calls)", async () => {
    mockFetch((route) => {
        expect.step(`fetch bundle: ${route.pathname}`);
        return bundles[route.pathname];
    });

    const first = await assets.getBundle("test.bundle");
    const second = await assets.getBundle("test.bundle");
    expect(second).toBe(first);
    expect.verifySteps(["fetch bundle: /web/bundle/test.bundle"]);
});

// ---------------------------------------------------------------------------
// ESM path (loadESMBundle) — same-document and cross-document
// ---------------------------------------------------------------------------

test("loadESMBundle: same-document imports specifiers and registers them on odoo.loader", async () => {
    const registered = [];
    patchWithCleanup(odoo.loader, {
        registerNativeModules: (modules) => registered.push(modules),
    });

    const spec = "data:text/javascript,export const answer = 42;";
    await assets.loadESMBundle([spec]);

    expect(registered.length).toBe(1);
    expect(registered[0][spec].answer).toBe(42);
});

/**
 * Build a detached iframe whose window carries a mock ``odoo.loader`` with the
 * given pre-registered modules, and capture every node appended to its head.
 * @param {Map<string, object>} modules
 */
const makeCrossDocTarget = (modules) => {
    const iframe = document.createElement("iframe");
    document.body.appendChild(iframe);
    const targetDoc = iframe.contentDocument;
    const targetWin = iframe.contentWindow;
    targetWin.odoo = { loader: { modules } };
    const captured = [];
    patchWithCleanup(targetDoc.head, { appendChild: (node) => captured.push(node) });
    return { iframe, targetDoc, targetWin, captured };
};

const getInjectedImports = (captured) => {
    const mapNode = captured.find((n) => n.type === "importmap");
    return mapNode ? JSON.parse(mapNode.textContent).imports : null;
};

test("loadESMBundle: cross-document builds bridge import map, reusing server bridges", async () => {
    const { iframe, targetWin, captured } = makeCrossDocTarget(
        new Map([
            ["@web/foo", { bar: 1, default: {} }], // runtime-only → data: bridge
            ["@web/served", { baz: 2 }], // covered by a server bridge → reuse it
            ["@web/own", { qux: 3 }], // covered by a server REAL FILE url
            ["@odoo/owl", { Component: 1 }], // always skipped
        ]),
    );
    const serverMap = {
        "@web/served": "/web/assets/esm/bridges/abc.js", // bridge URL
        "@web/own": "/web/own/static/src/own.js", // raw source file
        "@web/extra": "/web/assets/esm/bridges/def.js", // not loaded at runtime
    };

    const promise = assets.loadESMBundle(["@web/served"], {
        targetDoc: iframe.contentDocument,
        importMap: serverMap,
    });
    const imports = getInjectedImports(captured);

    // @web/foo: runtime-only → data: bridge for the bare spec AND its file URL
    // (``specToModuleUrl("@web/foo")`` === "/web/static/src/foo.js").
    expect(imports["@web/foo"].startsWith("data:")).toBe(true);
    expect(imports["/web/static/src/foo.js"]).toBe(imports["@web/foo"]);
    const fooSrc = decodeURIComponent(
        imports["@web/foo"].slice("data:text/javascript,".length),
    );
    expect(fooSrc.includes('odoo.loader.modules.get("@web/foo")')).toBe(true);
    expect(fooSrc.includes("export const bar = _m?.bar;")).toBe(true);

    // @web/served: server BRIDGE reused; no data: URI generated; file URL → bridge.
    expect(imports["@web/served"]).toBe("/web/assets/esm/bridges/abc.js");
    expect(imports["/web/static/src/served.js"]).toBe("/web/assets/esm/bridges/abc.js");

    // @web/own: server provides a RAW FILE → bare spec resolves to it (server
    // wins), but the relative-import URL must NOT point at the raw file (that
    // would re-evaluate); it stays a loader-re-exporting data: bridge.
    expect(imports["@web/own"]).toBe("/web/own/static/src/own.js");
    expect(imports["/web/static/src/own.js"].startsWith("data:")).toBe(true);

    // @odoo/owl is never bridged.
    expect(imports["@odoo/owl"]).toBe(undefined);

    // Server-only entry (not loaded at runtime) is still merged in.
    expect(imports["@web/extra"]).toBe("/web/assets/esm/bridges/def.js");

    // Resolve the pending load by firing the done event the injected script
    // would have dispatched.
    const scriptNode = captured.find((n) => n.type === "module");
    expect(Boolean(scriptNode)).toBe(true);
    const token = scriptNode.textContent.match(/__odoo_esm_bundle_loaded_(\d+)/)[1];
    targetWin.dispatchEvent(new Event(`__odoo_esm_bundle_loaded_${token}`));
    await expect(promise).resolves.toBe(undefined);

    iframe.remove();
});

test("loadESMBundle: cross-document rejects with the injected script's error detail", async () => {
    const { iframe, targetWin, captured } = makeCrossDocTarget(new Map());

    const promise = assets.loadESMBundle(["@web/x"], {
        targetDoc: iframe.contentDocument,
        importMap: { "@web/x": "data:text/javascript,export default 1" },
    });
    const scriptNode = captured.find((n) => n.type === "module");
    const token = scriptNode.textContent.match(/__odoo_esm_bundle_error_(\d+)/)[1];
    targetWin.dispatchEvent(
        new CustomEvent(`__odoo_esm_bundle_error_${token}`, {
            detail: new Error("boom in iframe"),
        }),
    );
    await expect(promise).rejects.toThrow(/boom in iframe/);

    iframe.remove();
});
