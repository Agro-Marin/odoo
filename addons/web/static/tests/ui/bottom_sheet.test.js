// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import { animationFrame, runAllTimers } from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import {
    defineStyle,
    mountWithCleanup,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { router, routerBus } from "@web/core/browser/router";
import { RouterEvent } from "@web/core/events";
import { BottomSheet } from "@web/ui/bottom_sheet/bottom_sheet";

test("hardware Back closes only the topmost of stacked sheets", async () => {
    class Child extends Component {
        static template = xml`<div class="sheet-child"/>`;
        static props = ["*"];
    }

    const sheet1 = await mountWithCleanup(BottomSheet, {
        props: { component: Child, close: () => {} },
    });
    await animationFrame();
    const sheet2 = await mountWithCleanup(BottomSheet, {
        props: { component: Child, close: () => {} },
    });
    await animationFrame();
    expect(router.ephemeralDepth).toBe(2);

    browser.history.back();
    expect(sheet2.state.isDismissing).toBe(true);
    expect(sheet1.state.isDismissing).toBe(false);
    expect(router.ephemeralDepth).toBe(1);

    browser.history.back();
    expect(sheet1.state.isDismissing).toBe(true);
    expect(router.ephemeralDepth).toBe(0);
});

test("hardware Back pressed while dismissing consumes the synthetic history entry", async () => {
    class Child extends Component {
        static template = xml`<div class="sheet-child"/>`;
        static props = ["*"];
    }

    const sheet = await mountWithCleanup(BottomSheet, {
        props: { component: Child, close: () => {} },
    });
    await animationFrame();
    expect(router.ephemeralDepth).toBe(1);

    sheet.slideOut();
    expect(sheet.state.isDismissing).toBe(true);

    browser.history.back();
    expect(router.ephemeralDepth).toBe(0);
});

test("closing a non-topmost sheet does not leak its history entry", async () => {
    class Child extends Component {
        static template = xml`<div class="sheet-child"/>`;
        static props = ["*"];
    }

    const sheet1 = await mountWithCleanup(BottomSheet, {
        props: { component: Child, close: () => {} },
    });
    await animationFrame();
    const sheet2 = await mountWithCleanup(BottomSheet, {
        props: { component: Child, close: () => {} },
    });
    await animationFrame();
    expect(router.ephemeralDepth).toBe(2);

    // Close the sheet UNDER the top one, programmatically: its entry is buried
    // and cannot be dropped yet.
    sheet1.__owl__.destroy();
    await animationFrame();
    expect(router.ephemeralDepth).toBe(2);

    sheet2.__owl__.destroy();
    await animationFrame();

    expect(router.ephemeralDepth).toBe(0);
    expect(browser.history.state?.ephemeralDepth).toBe(undefined);
});

test("a sheet's history entry keeps the router state visible", async () => {
    class Child extends Component {
        static template = xml`<div class="sheet-child"/>`;
        static props = ["*"];
    }
    browser.history.replaceState(
        { nextState: { action: 42 } },
        "",
        browser.location.href,
    );

    const sheet = await mountWithCleanup(BottomSheet, {
        props: { component: Child, close: () => {} },
    });
    await animationFrame();

    // The route did not change just because a sheet slid up.
    expect(browser.history.state.nextState.action).toBe(42);
    expect(browser.history.state.skipRouteChange).toBe(true);

    sheet.__owl__.destroy();
    await animationFrame();
    expect(browser.history.state.nextState.action).toBe(42);
});

test("opening and closing a sheet never triggers a route change", async () => {
    class Child extends Component {
        static template = xml`<div class="sheet-child"/>`;
        static props = ["*"];
    }
    router.pushState({ action: 42 });
    await runAllTimers();
    routerBus.addEventListener(RouterEvent.ROUTE_CHANGE, () =>
        expect.step("ROUTE_CHANGE"),
    );

    const sheet = await mountWithCleanup(BottomSheet, {
        props: { component: Child, close: () => {} },
    });
    await animationFrame();
    sheet.__owl__.destroy();
    await animationFrame();
    await runAllTimers();
    expect.verifySteps([]);

    // Same for the hardware-Back path.
    const sheet2 = await mountWithCleanup(BottomSheet, {
        props: { component: Child, close: () => {} },
    });
    await animationFrame();
    browser.history.back();
    await animationFrame();
    await runAllTimers();
    expect(sheet2.state.isDismissing).toBe(true);
    expect.verifySteps([]);
});

// REGRESSION-BLOCK
const animEnd = (sel, name) =>
    queryOne(sel).dispatchEvent(
        new AnimationEvent("animationend", { bubbles: true, animationName: name }),
    );

class AnimatedChild extends Component {
    static template = xml`<div class="sheet-child"><span class="inner-animation"/></div>`;
    static props = ["*"];
}

test("a descendant's animationend does not cut the dismiss animation short", async () => {
    let closed = 0;
    const sheet = await mountWithCleanup(BottomSheet, {
        props: { component: AnimatedChild, close: () => closed++ },
    });
    await animationFrame();
    sheet.prefersReducedMotion = false;
    sheet.slideOut();
    await animationFrame();

    animEnd(".inner-animation", "spin");
    expect(closed).toBe(0);

    animEnd(".o_bottom_sheet_sheet", "bottom-sheet-out");
    expect(closed).toBe(1);
});

test("a descendant's animationend does not enable snapping before the slide-in ends", async () => {
    const sheet = await mountWithCleanup(BottomSheet, {
        props: { component: AnimatedChild, close: () => {} },
    });
    sheet.prefersReducedMotion = false;
    sheet.state.isSnappingEnabled = false;
    sheet.initializeSheet();
    await animationFrame();

    animEnd(".inner-animation", "spin");
    expect(sheet.state.isSnappingEnabled).toBe(false);

    animEnd(".o_bottom_sheet_sheet", "bottom-sheet-in");
    expect(sheet.state.isSnappingEnabled).toBe(true);
});

test("the body carries the requested role, and none by default", async () => {
    await mountWithCleanup(BottomSheet, {
        props: { component: AnimatedChild, close: () => {}, role: "menu" },
    });
    await animationFrame();
    expect(".o_bottom_sheet_body").toHaveAttribute("role", "menu");

    await mountWithCleanup(BottomSheet, {
        props: { component: AnimatedChild, close: () => {} },
    });
    await animationFrame();
    expect(".o_bottom_sheet_body:last").not.toHaveAttribute("role");
});

test("a hosted component receives a bound close, like it does from a popover", async () => {
    /** @type {any} */
    let childProps = null;
    class Child extends Component {
        static template = xml`<div class="sheet-child"/>`;
        static props = ["*"];
        setup() {
            childProps = this.props;
        }
    }

    const sheet = await mountWithCleanup(BottomSheet, {
        props: { component: Child, close: () => expect.step("close") },
    });
    await animationFrame();
    sheet.prefersReducedMotion = true;

    expect(typeof childProps.close).toBe("function");
    childProps.close();
    expect.verifySteps(["close"]);
});

// SLOT-API-BLOCK
test("a slot-only sheet renders, and its back slot prop routes to onBack", async () => {
    class Host extends Component {
        static components = { BottomSheet };
        static props = ["*"];
        static template = xml`
            <BottomSheet close="() => {}" onBack="() => this.onBack()">
                <t t-set-slot="default" t-slot-scope="sheet">
                    <div class="slotted"/>
                    <button class="slot-back" t-on-click="() => sheet.back()">b</button>
                </t>
            </BottomSheet>`;
        onBack() {
            expect.step("back");
        }
    }

    await mountWithCleanup(Host);
    await animationFrame();
    expect(".slotted").toHaveCount(1);

    queryOne(".slot-back").click();
    expect.verifySteps(["back"]);
});

test("a focus-trapping sheet is announced as modal, a non-trapping one is not", async () => {
    class Child extends Component {
        static template = xml`<div class="sheet-child"/>`;
        static props = ["*"];
    }
    await mountWithCleanup(BottomSheet, {
        props: { component: Child, close: () => {} },
    });
    await animationFrame();
    expect(".o_bottom_sheet_sheet").toHaveAttribute("role", "dialog");
    expect(".o_bottom_sheet_sheet").toHaveAttribute("aria-modal", "true");

    // Dropdown opens its menu as a sheet without taking the active element:
    // the page behind stays reachable, so the sheet must not claim modality.
    await mountWithCleanup(BottomSheet, {
        props: { component: Child, close: () => {}, setActiveElement: false },
    });
    await animationFrame();
    expect(".o_bottom_sheet_sheet:last").not.toHaveAttribute("aria-modal");
});

// DISMISS-GESTURE-BLOCK
// Scrolling the rail below `dismissThreshold` IS the drag-to-dismiss gesture,
// and `updateDimensions` rewrites `--sheet-height` on that same rail when the
// viewport changes. Nothing pinned the boundary between the two, so a
// reflow-driven scroll event was free to read as a dismissal — which on mobile
// would mean focusing an input inside a sheet closes the sheet.
test.tags("mobile");
test("a viewport change (virtual keyboard) does not dismiss the sheet", async () => {
    class Child extends Component {
        static template = xml`<div class="sheet-child"/>`;
        static props = ["*"];
    }
    const sheet = await mountWithCleanup(BottomSheet, {
        props: { component: Child, close: () => expect.step("closed") },
    });
    await animationFrame();
    await runAllTimers();
    expect(".sheet-child").toHaveCount(1);
    expect(sheet.state.isDismissing).toBe(false);

    patchWithCleanup(browser, {
        visualViewport: {
            width: 375,
            height: 300,
            addEventListener: () => {},
            removeEventListener: () => {},
        },
    });
    sheet.updateDimensions();
    sheet.scrollRailRef.el.dispatchEvent(new Event("scroll"));
    await runAllTimers();
    await animationFrame();

    expect(sheet.state.isDismissing).toBe(false);
    expect.verifySteps([]);
});

test.tags("mobile");
test("dragging the rail below the threshold dismisses the sheet", async () => {
    class Child extends Component {
        static template = xml`<div class="sheet-child"/>`;
        static props = ["*"];
    }
    const sheet = await mountWithCleanup(BottomSheet, {
        props: { component: Child, close: () => expect.step("closed") },
    });
    await animationFrame();
    await runAllTimers();
    expect(sheet.state.isDismissing).toBe(false);

    sheet.scrollRailRef.el.scrollTop = 0;
    sheet.scrollRailRef.el.dispatchEvent(new Event("scroll"));
    await runAllTimers();
    await animationFrame();

    expect(sheet.state.isDismissing).toBe(true);
    expect.verifySteps(["closed"]);
});

test("the sheet re-measures smaller when its content shrinks", async () => {
    // `measureDimensions` removed the INLINE `min-height`/`height`, which were
    // never set. The constraint it meant to lift is the stylesheet's
    // `min-height: var(--sheet-height)`, written from the PREVIOUS measurement,
    // so each re-measure was clamped to the size it was re-deriving and the
    // sheet could only grow. Unit tests load no stylesheet, which is exactly
    // why this survived -- so the real rule is injected here.
    defineStyle(`
        .o_bottom_sheet_sheet { min-height: var(--sheet-height); }
    `);
    class Child extends Component {
        static props = ["*"];
        static template = xml`<div class="sheet-child" t-attf-style="height: {{props.h}}px"/>`;
    }
    const sheet = await mountWithCleanup(BottomSheet, {
        props: { component: Child, componentProps: { h: 600 }, close: () => {} },
    });
    await animationFrame();
    const tall = sheet.measurements.naturalHeight;
    expect(tall).toBeGreaterThan(400);

    queryOne(".sheet-child").style.height = "40px";
    sheet.updateDimensions();

    expect(sheet.measurements.naturalHeight).toBeLessThan(tall, {
        message: `natural height stayed at ${sheet.measurements.naturalHeight}`,
    });
});

test("snapping is really suppressed while the sheet is re-measured", async () => {
    // `state.isSnappingEnabled = false; ...; = true` around a synchronous
    // re-layout is a no-op: Owl coalesces both writes into one render, so the
    // class never left the DOM and the browser stayed free to re-snap the rail
    // against snap points that were being rewritten underneath it.
    class Child extends Component {
        static props = ["*"];
        static template = xml`<div class="sheet-child" style="height:300px"/>`;
    }
    const sheet = await mountWithCleanup(BottomSheet, {
        props: { component: Child, close: () => {} },
    });
    await animationFrame();

    const seen = [];
    patchWithCleanup(sheet, {
        measureDimensions() {
            seen.push(this.scrollRailRef.el.style.getPropertyValue("scroll-snap-type"));
            return super.measureDimensions();
        },
    });

    sheet.updateDimensions();

    expect(seen).toEqual(["none"], {
        message: "snapping must be off at the moment the layout is forced",
    });
    // ...and restored afterwards, so the class-driven rule takes over again.
    expect(
        queryOne(".o_bottom_sheet_rail").style.getPropertyValue("scroll-snap-type"),
    ).toBe("");
});
