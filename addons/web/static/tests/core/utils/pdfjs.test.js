// @ts-check

import { describe, expect, getFixture, test } from "@odoo/hoot";
import { hidePDFJSButtons, withWasmDefault } from "@web/core/utils/pdfjs";

describe.current.tags("headless");

function makeIframe() {
    const iframe = document.createElement("iframe");
    getFixture().appendChild(iframe);
    return iframe;
}

test("applies immediately when the iframe document is already loaded", () => {
    const iframe = makeIframe();
    expect(iframe.contentDocument.readyState).toBe("complete");
    hidePDFJSButtons(iframe);
    const styleEl = iframe.contentDocument.head.querySelector("style");
    expect(styleEl).not.toBe(null);
    expect(styleEl.textContent).toInclude("#editorModeButtons");
    expect(styleEl.textContent).toInclude("display: none !important;");
});

test("a later call with different options updates the injected style", () => {
    const iframe = makeIframe();
    hidePDFJSButtons(iframe);
    const styleEl = iframe.contentDocument.head.querySelector("style");
    expect(styleEl.textContent).not.toInclude("#presentationMode");

    hidePDFJSButtons(iframe, { hidePresentation: true, hideRotation: true });
    expect(iframe.contentDocument.head.querySelectorAll("style")).toHaveLength(1);
    expect(styleEl.textContent).toInclude("button#presentationMode");
    expect(styleEl.textContent).toInclude("button#pageRotateCw");
});

test("resolves the iframe from a container root element", () => {
    const container = document.createElement("div");
    const iframe = document.createElement("iframe");
    container.appendChild(iframe);
    getFixture().appendChild(container);
    hidePDFJSButtons(container, { hideDownload: true });
    const styleEl = iframe.contentDocument.head.querySelector("style");
    expect(styleEl).not.toBe(null);
    expect(styleEl.textContent).toInclude("button#downloadButton");
});

function makeNamespaceLike(/** @type {any} */ getDocument) {
    const ns = {};
    Object.defineProperty(ns, "getDocument", {
        configurable: false,
        enumerable: true,
        value: getDocument,
        writable: false,
    });
    Object.defineProperty(ns, "GlobalWorkerOptions", {
        configurable: false,
        enumerable: true,
        value: {},
        writable: false,
    });
    return Object.freeze(ns);
}

test("wraps getDocument over a module namespace, whose exports cannot be assigned", () => {
    /** @type {any[]} */
    const calls = [];
    const lib = makeNamespaceLike((/** @type {any} */ params) => {
        calls.push(params);
        return "task";
    });
    expect(() => {
        Object.create(lib).getDocument = () => {};
    }).toThrow();

    const view = withWasmDefault(lib);
    expect(view.getDocument("/a.pdf")).toBe("task");
    expect(calls).toEqual([
        { url: "/a.pdf", wasmUrl: "/web/static/lib/pdfjs/web/wasm/" },
    ]);
    expect(view.GlobalWorkerOptions).toBe(lib.GlobalWorkerOptions);
});

test("getDocument normalises every source shape and keeps an explicit wasmUrl", () => {
    /** @type {any[]} */
    const calls = [];
    const lib = makeNamespaceLike((/** @type {any} */ params) => calls.push(params));
    const view = withWasmDefault(lib);
    const data = new Uint8Array([1, 2]);

    view.getDocument(new URL("https://example.test/a.pdf"));
    view.getDocument(data);
    view.getDocument({ url: "/b.pdf", wasmUrl: "/elsewhere/" });

    expect(calls[0].url.href).toBe("https://example.test/a.pdf");
    expect(calls[0].wasmUrl).toBe("/web/static/lib/pdfjs/web/wasm/");
    expect(calls[1].data).toBe(data);
    expect(calls[2].wasmUrl).toBe("/elsewhere/");
});
