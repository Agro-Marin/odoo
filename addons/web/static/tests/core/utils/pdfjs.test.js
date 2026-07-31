// @ts-check

import { describe, expect, getFixture, test } from "@odoo/hoot";
import { hidePDFJSButtons } from "@web/core/utils/pdfjs";

describe.current.tags("headless");

// The vendored pdf.js flavour (legacy vs modern dist) is gated in
// addons/web/tests/test_pdfjs_dist.py, against the bundle files themselves.
// It cannot be gated from here: asserting Map.prototype.getOrInsertComputed
// after loadPDFJS() passes on any browser that ships the method natively —
// Firefox 144, Safari 26.2, Chrome 145 and later — so the check would silently
// stop gating anything as soon as the runner's browser caught up, which is
// precisely the regression it was meant to catch (t24581).

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
