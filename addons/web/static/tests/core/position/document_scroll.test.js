// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { reposition } from "@web/core/position/utils";

describe.current.tags("headless");

/**
 * @param {(win: Window, doc: Document) => any} callback
 */
async function withScrollableDocument(callback) {
    const iframe = document.createElement("iframe");
    iframe.style.cssText = "width:600px;height:400px;border:0;";
    document.body.appendChild(iframe);
    try {
        await new Promise((resolve) => {
            iframe.addEventListener("load", resolve, { once: true });
            iframe.srcdoc = `<!doctype html><html><body style="margin:0;width:3000px;height:3000px"></body></html>`;
        });
        const win = /** @type {Window} */ (iframe.contentWindow);
        const doc = /** @type {Document} */ (iframe.contentDocument);
        return await callback(win, doc);
    } finally {
        iframe.remove();
    }
}

/**
 * @param {Window} win
 * @param {Document} doc
 * @param {import("@web/core/position/utils").ComputePositionOptions["position"]} position
 * @param {number} scrollLeft
 * @param {number} scrollTop
 */
function measure(win, doc, position, scrollLeft, scrollTop) {
    const target = doc.createElement("div");
    target.style.cssText = "position:absolute;width:40px;height:20px;";
    doc.body.appendChild(target);
    const popper = doc.createElement("div");
    popper.style.cssText = "width:200px;height:50px;";
    doc.body.appendChild(popper);

    target.style.left = `${scrollLeft + 200}px`;
    target.style.top = `${scrollTop + 150}px`;
    win.scrollTo(scrollLeft, scrollTop);

    reposition(popper, target, { position, margin: 0 });
    const popperBox = popper.getBoundingClientRect();
    const targetBox = target.getBoundingClientRect();
    const result = [
        Math.round(popperBox.left - targetBox.left),
        Math.round(popperBox.top - targetBox.top),
    ];
    target.remove();
    popper.remove();
    return result;
}

test("a horizontally scrolled document does not displace the popper", async () => {
    await withScrollableDocument((win, doc) => {
        const unscrolled = measure(win, doc, "bottom-start", 0, 0);
        expect(measure(win, doc, "bottom-start", 300, 0)).toEqual(unscrolled, {
            message: "scrollLeft=300 must not move the popper relative to its target",
        });
        expect(measure(win, doc, "bottom-start", 1200, 0)).toEqual(unscrolled, {
            message: "scrollLeft=1200 used to push the popper out of the viewport",
        });
    });
});

test("a vertically scrolled document does not displace the popper", async () => {
    await withScrollableDocument((win, doc) => {
        const unscrolled = measure(win, doc, "bottom-start", 0, 0);
        expect(measure(win, doc, "bottom-start", 0, 400)).toEqual(unscrolled);
        expect(measure(win, doc, "bottom-start", 300, 400)).toEqual(unscrolled);
    });
});

test("a horizontal direction is stable under scroll too", async () => {
    await withScrollableDocument((win, doc) => {
        const unscrolled = measure(win, doc, "right-middle", 0, 0);
        expect(measure(win, doc, "right-middle", 300, 0)).toEqual(unscrolled);
        expect(measure(win, doc, "right-middle", 1200, 400)).toEqual(unscrolled);
    });
});
