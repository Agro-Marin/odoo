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
            seen.push(
                this.scrollRailRef.el?.style.getPropertyValue("scroll-snap-type"),
            );
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

test.tags("mobile");
test("a shrinking visual viewport never sizes the sheet past it", async () => {
    // `applyDimensions` measures the VISUAL viewport, which is what a virtual
    // keyboard shrinks. Emitting that measurement as a ratio in `dvh` -- a
    // LAYOUT viewport unit -- silently mixed the two: the backend's viewport
    // meta leaves `interactive-widget` at its default, so the layout viewport
    // does not follow the keyboard. The sheet ended up with a `min-height`
    // larger than the `max-height` meant to cap it, and min-height wins.
    class Tall extends Component {
        static template = xml`<div class="sheet-child" style="height: 900px">tall</div>`;
        static props = ["*"];
    }
    const sheet = await mountWithCleanup(BottomSheet, {
        props: { component: Tall, close: () => {} },
    });
    await animationFrame();
    await runAllTimers();

    patchWithCleanup(browser, {
        visualViewport: {
            width: 375,
            height: 300,
            addEventListener: () => {},
            removeEventListener: () => {},
        },
    });
    sheet.updateDimensions();
    await animationFrame();

    const sheetEl = queryOne(".o_bottom_sheet_sheet");
    const { minHeight, maxHeight } = getComputedStyle(sheetEl);
    expect(parseFloat(minHeight)).toBeLessThan(parseFloat(maxHeight) + 1);
    expect(parseFloat(maxHeight)).toBe(300);
    expect(sheetEl.getBoundingClientRect().height).toBeLessThan(301);
});

/** @param {number} height */
function resizeVisualViewport(height) {
    patchWithCleanup(browser, {
        visualViewport: {
            width: 375,
            height,
            addEventListener: () => {},
            removeEventListener: () => {},
        },
    });
}

test.tags("mobile");
test("the sheet grows back once the viewport does", async () => {
    // Sibling of "re-measures smaller when its content shrinks": that one lifts
    // the stylesheet's `min-height: var(--sheet-height)` so the sheet can shrink.
    // Its mirror, `max-height: var(--sheet-max-height)`, was still in force
    // during the measurement, so once a virtual keyboard shrank the viewport the
    // natural height was capped at the shrunken value and never recovered.
    class Tall extends Component {
        static template = xml`<div class="sheet-child" style="height: 900px">tall</div>`;
        static props = ["*"];
    }
    const sheet = await mountWithCleanup(BottomSheet, {
        props: { component: Tall, close: () => {} },
    });
    await animationFrame();
    await runAllTimers();
    const full = sheet.measurements.initialHeight;
    expect(full).toBeGreaterThan(500);

    resizeVisualViewport(300);
    sheet.updateDimensions();
    await animationFrame();
    expect(sheet.measurements.initialHeight).toBeLessThan(full);

    resizeVisualViewport(667);
    sheet.updateDimensions();
    await animationFrame();
    expect(sheet.measurements.initialHeight).toBe(full);
});

test.tags("mobile");
test("a viewport change keeps the rail anchored to the sheet", async () => {
    // The rail's scrollable extent IS the dismiss area, so re-measuring without
    // re-anchoring left the sheet part-dragged against the new extent. Below
    // `dismissThreshold` that reads as the drag-to-dismiss gesture, so putting
    // the keyboard away closed the sheet.
    class Tall extends Component {
        static template = xml`<div class="sheet-child" style="height: 900px">tall</div>`;
        static props = ["*"];
    }
    const sheet = await mountWithCleanup(BottomSheet, {
        props: { component: Tall, close: () => expect.step("closed") },
    });
    await animationFrame();
    await runAllTimers();
    const rail = sheet.scrollRailRef.el;
    expect(Math.round(rail.scrollTop)).toBe(
        Math.round(sheet.measurements.initialHeight),
    );

    for (const height of [300, 667]) {
        resizeVisualViewport(height);
        sheet.updateDimensions();
        await animationFrame();
        expect(Math.round(rail.scrollTop)).toBe(
            Math.round(sheet.measurements.initialHeight),
            { message: `rail left unanchored at visual viewport ${height}` },
        );
    }

    rail.dispatchEvent(new Event("scroll"));
    await runAllTimers();
    await animationFrame();
    expect(sheet.state.isDismissing).toBe(false);
    expect.verifySteps([]);
});

const animEvent = (sel, type, name) =>
    queryOne(sel).dispatchEvent(
        new AnimationEvent(type, { bubbles: true, animationName: name }),
    );

// `.o_bottom_sheet_dismissing` overrides `.o_bottom_sheet_ready` at equal
// specificity, so raising it swaps `animation-name` on the element still
// running the slide-in and the browser cancels that animation right there.
// Chrome emits `start:in, cancel:in, start:out, end:out`. A listener that only
// checked `ev.target` accepted the cancellation as "the slide-out finished", so
// a sheet dismissed inside its 400ms opening animation vanished with no
// slide-out and closed ~200ms early.
test("the slide-in's cancellation is not the slide-out's end", async () => {
    let closed = 0;
    const sheet = await mountWithCleanup(BottomSheet, {
        props: { component: AnimatedChild, close: () => closed++ },
    });
    await animationFrame();
    sheet.prefersReducedMotion = false;
    sheet.slideOut();
    await animationFrame();

    animEvent(".o_bottom_sheet_sheet", "animationcancel", "bottom-sheet-in");
    expect(closed).toBe(0, { message: "the cancelled slide-in closed the sheet" });

    animEvent(".o_bottom_sheet_sheet", "animationend", "bottom-sheet-out");
    expect(closed).toBe(1);
});

test("an animation the sheet does not play never closes it", async () => {
    let closed = 0;
    const sheet = await mountWithCleanup(BottomSheet, {
        props: { component: AnimatedChild, close: () => closed++ },
    });
    await animationFrame();
    sheet.prefersReducedMotion = false;
    sheet.slideOut();
    await animationFrame();

    animEvent(".o_bottom_sheet_sheet", "animationend", "some-other-animation");
    expect(closed).toBe(0);
});

// The mirror of the above: snapping is what `slideOut` has just turned off, so
// the slide-in being cancelled must not turn it back on mid-dismissal.
test("a cancelled slide-in does not enable snapping", async () => {
    const sheet = await mountWithCleanup(BottomSheet, {
        props: { component: AnimatedChild, close: () => {} },
    });
    sheet.prefersReducedMotion = false;
    sheet.state.isSnappingEnabled = false;
    sheet.initializeSheet();
    await animationFrame();

    animEvent(".o_bottom_sheet_sheet", "animationcancel", "bottom-sheet-in");
    expect(sheet.state.isSnappingEnabled).toBe(false);

    animEvent(".o_bottom_sheet_sheet", "animationend", "bottom-sheet-in");
    expect(sheet.state.isSnappingEnabled).toBe(true);
});
