// @ts-check

import { describe, expect, getFixture, test } from "@odoo/hoot";
import { hidePDFJSButtons, loadPDFJS } from "@web/core/utils/pdfjs";

describe.current.tags("headless");

test("the vendored bundle brings its own Map.prototype.getOrInsertComputed", async () => {
    // Guards the distribution flavour, which is a silent failure mode: pdf.js
    // calls Map.prototype.getOrInsertComputed with no feature detection, no
    // shipping browser implements it yet, and only the LEGACY dist bundles the
    // core-js polyfill (see versions.json). Vendor the modern dist by mistake
    // and every PDF preview breaks — but nothing surfaces it, because the call
    // site is a fire-and-forget setPdfThumbnail() whose rejection the global
    // handler swallows. The other tests in this file passed green throughout
    // exactly such a regression (t24581).
    //
    // Asserted after the import, not before: the polyfill is what the bundle
    // installs, so a browser that already ships the method natively satisfies
    // this too, and the day that is universal the check simply stops being
    // load-bearing rather than starting to lie.
    await loadPDFJS();
    expect(typeof Map.prototype.getOrInsertComputed).toBe("function");

    const cache = new Map();
    expect(cache.getOrInsertComputed("k", () => 42)).toBe(42);
    expect(cache.get("k")).toBe(42);
    // Computes once: a second read must not re-run the callback.
    expect(cache.getOrInsertComputed("k", () => 99)).toBe(42);
});

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
