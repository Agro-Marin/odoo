// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import { animationFrame, runAllTimers } from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
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
