// @ts-check

import { beforeEach, describe, expect, getFixture, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { localization } from "@web/core/l10n/localization";
import { createPopper } from "@web/libs/popper_compat";

beforeEach(() => patchWithCleanup(localization, { direction: "ltr" }));

/**
 * @param {{ refStyle?: string, popStyle?: string, arrow?: boolean }} [options]
 */
function build({ refStyle = "", popStyle = "", arrow = false } = {}) {
    const fixture = getFixture();
    const reference = document.createElement("button");
    reference.style.cssText = `position:absolute;width:80px;height:20px;${refStyle}`;
    const popper = document.createElement("div");
    popper.style.cssText = `width:120px;height:40px;${popStyle}`;
    if (arrow) {
        const el = document.createElement("div");
        el.className = "tooltip-arrow";
        el.style.cssText = "width:10px;height:10px";
        popper.appendChild(el);
    }
    /** @type {HTMLElement} */ (fixture).append(reference, popper);
    return { reference, popper };
}

const centredRefStyle = () =>
    `top:200px;left:${Math.round((document.documentElement.clientWidth - 80) / 2)}px`;

describe("placement reporting", () => {
    test("writes the resolved placement to data-popper-placement", async () => {
        const { reference, popper } = build({ refStyle: "top:200px;left:200px" });
        const instance = createPopper(reference, popper, { placement: "bottom" });
        expect(popper.getAttribute("data-popper-placement")).toBe("bottom");
        instance.destroy();
    });

    test("keeps the -start / -end variant in the reported placement", async () => {
        const { reference, popper } = build({ refStyle: "top:200px;left:200px" });
        const instance = createPopper(reference, popper, { placement: "bottom-start" });
        expect(popper.getAttribute("data-popper-placement")).toBe("bottom-start");
        instance.destroy();
    });

    test("destroy() removes the attribute it added", async () => {
        const { reference, popper } = build({ refStyle: "top:200px;left:200px" });
        createPopper(reference, popper, { placement: "top" }).destroy();
        expect(popper.hasAttribute("data-popper-placement")).toBe(false);
    });
});

describe("Bootstrap's modifiers", () => {
    test("preSetPlacement runs with the resolved placement on state", async () => {
        const { reference, popper } = build({ refStyle: "top:200px;left:200px" });
        /** @type {any[]} */
        const seen = [];
        const instance = createPopper(reference, popper, {
            placement: "bottom",
            modifiers: [
                {
                    name: "preSetPlacement",
                    enabled: true,
                    phase: "beforeMain",
                    fn: (/** @type {any} */ data) => seen.push(data.state.placement),
                },
            ],
        });
        expect(seen).toEqual(["bottom"]);
        instance.destroy();
    });

    test("applyStyles:false leaves the element untouched (static dropdown)", async () => {
        const { reference, popper } = build({ refStyle: "top:200px;left:200px" });
        const before = popper.style.cssText;
        const instance = createPopper(reference, popper, {
            placement: "bottom",
            modifiers: [{ name: "applyStyles", enabled: false }],
        });
        expect(popper.style.cssText).toBe(before);
        expect(popper.hasAttribute("data-popper-placement")).toBe(false);
        instance.destroy();
    });

    test("the offset modifier's distance separates popper from reference", async () => {
        const { reference, popper } = build({ refStyle: "top:200px;left:200px" });
        const flush = createPopper(reference, popper, { placement: "bottom" });
        const flushTop = parseFloat(popper.style.top);
        flush.destroy();

        const offset = createPopper(reference, popper, {
            placement: "bottom",
            modifiers: [{ name: "offset", options: { offset: [0, 25] } }],
        });
        expect(parseFloat(popper.style.top) - flushTop).toBeCloseTo(25, {
            margin: 1.5,
        });
        offset.destroy();
    });

    test("the offset modifier accepts Bootstrap's function form", async () => {
        const { reference, popper } = build({ refStyle: "top:200px;left:200px" });
        const flush = createPopper(reference, popper, { placement: "bottom" });
        const flushTop = parseFloat(popper.style.top);
        flush.destroy();

        const instance = createPopper(reference, popper, {
            placement: "bottom",
            modifiers: [{ name: "offset", options: { offset: () => [0, 12] } }],
        });
        expect(parseFloat(popper.style.top) - flushTop).toBeCloseTo(12, {
            margin: 1.5,
        });
        instance.destroy();
    });

    test("skidding shifts along the cross axis", async () => {
        const { reference, popper } = build({ refStyle: "top:200px;left:200px" });
        const flush = createPopper(reference, popper, { placement: "bottom" });
        const flushLeft = parseFloat(popper.style.left);
        flush.destroy();

        const instance = createPopper(reference, popper, {
            placement: "bottom",
            modifiers: [{ name: "offset", options: { offset: [15, 0] } }],
        });
        expect(parseFloat(popper.style.left) - flushLeft).toBeCloseTo(15, {
            margin: 1.5,
        });
        instance.destroy();
    });

    test("an unknown modifier is ignored rather than throwing", async () => {
        const { reference, popper } = build({ refStyle: "top:200px;left:200px" });
        const instance = createPopper(reference, popper, {
            placement: "bottom",
            modifiers: [{ name: "computeStyles", options: { gpuAcceleration: false } }],
        });
        expect(popper.getAttribute("data-popper-placement")).toBe("bottom");
        instance.destroy();
    });
});

describe("arrow", () => {
    test("the arrow is offset along the popper's cross axis", async () => {
        const { reference, popper } = build({
            refStyle: "top:200px;left:200px",
            arrow: true,
        });
        const instance = createPopper(reference, popper, {
            placement: "bottom",
            modifiers: [{ name: "arrow", options: { element: ".tooltip-arrow" } }],
        });
        const arrow = /** @type {HTMLElement} */ (
            popper.querySelector(".tooltip-arrow")
        );
        expect(arrow.style.left).not.toBe("");
        expect(arrow.style.top).toBe("");
        instance.destroy();
    });

    test("the arrow stays within the popper's bounds", async () => {
        const { reference, popper } = build({
            refStyle: "top:200px;left:0px",
            arrow: true,
        });
        const instance = createPopper(reference, popper, {
            placement: "bottom",
            modifiers: [{ name: "arrow", options: { element: ".tooltip-arrow" } }],
        });
        const arrow = /** @type {HTMLElement} */ (
            popper.querySelector(".tooltip-arrow")
        );
        const left = parseFloat(arrow.style.left);
        expect(left).toBeGreaterThanOrEqual(0);
        expect(left).toBeLessThanOrEqual(popper.getBoundingClientRect().width);
        instance.destroy();
    });
});

describe("RTL", () => {
    test("a physical placement is honoured, not mirrored again", async () => {
        patchWithCleanup(localization, { direction: "rtl" });
        const { reference, popper } = build({ refStyle: centredRefStyle() });
        const instance = createPopper(reference, popper, { placement: "left" });
        const ref = reference.getBoundingClientRect();
        expect(popper.getBoundingClientRect().right).toBeLessThanOrEqual(ref.left + 1);
        expect(popper.getAttribute("data-popper-placement")).toBe("left");
        instance.destroy();
    });

    test.tags("desktop");
    test("the reported placement stays physical in RTL", async () => {
        patchWithCleanup(localization, { direction: "rtl" });
        const { reference, popper } = build({ refStyle: centredRefStyle() });
        const instance = createPopper(reference, popper, { placement: "right" });
        const ref = reference.getBoundingClientRect();
        expect(popper.getBoundingClientRect().left).toBeGreaterThanOrEqual(
            ref.right - 1,
        );
        expect(popper.getAttribute("data-popper-placement")).toBe("right");
        instance.destroy();
    });

    test.tags("desktop");
    test("the -start variant is not swapped in RTL", async () => {
        patchWithCleanup(localization, { direction: "rtl" });
        const { reference, popper } = build({ refStyle: centredRefStyle() });
        const instance = createPopper(reference, popper, { placement: "bottom-start" });
        const ref = reference.getBoundingClientRect();
        expect(popper.getBoundingClientRect().left).toBeCloseTo(ref.left, {
            margin: 1.5,
        });
        expect(popper.getAttribute("data-popper-placement")).toBe("bottom-start");
        instance.destroy();
    });
});

describe("lifecycle", () => {
    test("update() is safe once the popper has left the document", async () => {
        const { reference, popper } = build({ refStyle: "top:200px;left:200px" });
        const instance = createPopper(reference, popper, { placement: "bottom" });
        popper.remove();
        expect(() => instance.update()).not.toThrow();
        instance.destroy();
    });

    test("destroy() detaches the viewport listeners", async () => {
        const { reference, popper } = build({ refStyle: "top:200px;left:200px" });
        const instance = createPopper(reference, popper, { placement: "bottom" });
        instance.destroy();
        popper.setAttribute("data-popper-placement", "sentinel");
        window.dispatchEvent(new Event("resize"));
        expect(popper.getAttribute("data-popper-placement")).toBe("sentinel");
    });
});
