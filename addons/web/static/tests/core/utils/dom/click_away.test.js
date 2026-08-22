// @ts-check

import { describe, expect, getFixture, test } from "@odoo/hoot";
import { Component, xml } from "@odoo/owl";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { useClickAway } from "@web/core/utils/dom/click_away";

describe.current.tags("headless");

/**
 * @param {Parameters<typeof useClickAway>[1]} [options]
 */
async function mountClickAway(options) {
    /** @type {Node[]} */
    const calls = [];
    class Probe extends Component {
        static template = xml`<div class="probe"><span class="inside">x</span></div>`;
        static props = {};
        setup() {
            useClickAway((node) => calls.push(/** @type {Node} */ (node)), options);
        }
    }
    const component = await mountWithCleanup(Probe);
    return { calls, component };
}

/** @returns {HTMLElement} */
function fixture() {
    return /** @type {any} */ (getFixture());
}

/**
 * @param {EventTarget} target
 */
function pointerDown(target) {
    target.dispatchEvent(
        new PointerEvent("pointerdown", { bubbles: true, composed: true }),
    );
}

describe("pointerdown", () => {
    test("fires with the deepest node of the composed path", async () => {
        const { calls } = await mountClickAway();
        const inside = /** @type {HTMLElement} */ (fixture().querySelector(".inside"));
        pointerDown(/** @type {Element} */ (inside));
        expect(calls).toEqual([inside]);
    });

    test("fires for a pointerdown anywhere, including outside the component", async () => {
        const { calls } = await mountClickAway();
        const outside = document.createElement("div");
        fixture().appendChild(outside);
        pointerDown(outside);
        expect(calls).toEqual([outside]);
    });
});

describe("blur", () => {
    test("an IFRAME taking focus is reported as a click away", async () => {
        const { calls } = await mountClickAway();
        const iframe = document.createElement("iframe");
        fixture().appendChild(iframe);
        window.dispatchEvent(new FocusEvent("blur", { relatedTarget: iframe }));
        expect(calls).toEqual([iframe]);
    });

    test("blurring to anything else is not a click away", async () => {
        const { calls } = await mountClickAway();
        const button = document.createElement("button");
        fixture().appendChild(button);
        window.dispatchEvent(new FocusEvent("blur", { relatedTarget: button }));
        expect(calls).toEqual([]);
    });
});

describe("navigation", () => {
    test("a popstate that did not change the url is ignored", async () => {
        const { calls } = await mountClickAway();
        window.dispatchEvent(new PopStateEvent("popstate"));
        expect(calls).toEqual([]);
    });

    test("a popstate after the url changed closes", async () => {
        const { calls } = await mountClickAway();
        browser.location.href = `${browser.location.origin}/odoo/click-away-probe`;
        window.dispatchEvent(new PopStateEvent("popstate"));
        expect(calls).toEqual([document.documentElement]);
    });
});

describe("iframes", () => {
    /**
     * @param {Element} parent
     */
    async function addIframe(parent) {
        const iframe = document.createElement("iframe");
        parent.appendChild(iframe);
        await new Promise((resolve) => {
            iframe.addEventListener("load", resolve, { once: true });
            iframe.srcdoc = "<!doctype html><html><body><b id=in>i</b></body></html>";
        });
        return iframe;
    }

    test("a pointerdown inside a same-origin iframe closes", async () => {
        const iframe = await addIframe(fixture());
        const { calls } = await mountClickAway();
        const inner = /** @type {Document} */ (iframe.contentDocument).getElementById(
            "in",
        );
        pointerDown(/** @type {Element} */ (inner));
        expect(calls).toEqual([iframe], {
            message: "the iframe element itself is reported, not its inner node",
        });
    });

    test("an iframe inside the component's own content does not close it", async () => {
        const host = document.createElement("div");
        fixture().appendChild(host);
        const iframe = await addIframe(host);
        const { calls } = await mountClickAway({ getContentEl: () => host });
        const inner = /** @type {Document} */ (iframe.contentDocument).getElementById(
            "in",
        );
        pointerDown(/** @type {Element} */ (inner));
        expect(calls).toEqual([]);
    });

    test("a frame that refuses inspection is skipped, not thrown out of", async () => {
        const iframe = document.createElement("iframe");
        fixture().appendChild(iframe);
        Object.defineProperty(iframe, "contentWindow", {
            get: () => ({
                get addEventListener() {
                    throw new DOMException("blocked a frame", "SecurityError");
                },
            }),
            configurable: true,
        });
        let error = null;
        try {
            await mountClickAway();
        } catch (e) {
            error = e;
        }
        expect(error).toBe(null);
    });
});

describe("teardown", () => {
    test("destroying the owner stops the callbacks", async () => {
        const { calls, component } = await mountClickAway();
        const outside = document.createElement("div");
        fixture().appendChild(outside);
        pointerDown(outside);
        expect(calls.length).toBe(1);

        component.__owl__.app.destroy();
        pointerDown(outside);
        expect(calls.length).toBe(1, {
            message: "the window listeners must not outlive the component",
        });
    });
});
