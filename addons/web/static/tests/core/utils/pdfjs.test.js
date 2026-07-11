// @ts-check

import { describe, expect, getFixture, test } from "@odoo/hoot";
import { hidePDFJSButtons } from "@web/core/utils/pdfjs";

describe.current.tags("headless");

function makeIframe() {
    const iframe = document.createElement("iframe");
    getFixture().appendChild(iframe);
    return iframe;
}

test("applies immediately when the iframe document is already loaded", () => {
    // The viewer iframe may have fired "load" before the call (fast cache,
    // re-mount): waiting for a future "load" event alone would never inject
    // the style and the buttons would stay visible.
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
    // Same element, updated content — no duplicated <style> nodes.
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
