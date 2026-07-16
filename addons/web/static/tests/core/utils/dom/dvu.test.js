// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { resize } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, useState, xml } from "@odoo/owl";
import { mountWithCleanup, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { getViewportDimensions, useViewportChange } from "@web/core/utils/dom/dvu";

describe.current.tags("desktop");

test("getViewportDimensions: prefers visualViewport when present", () => {
    // visualViewport reflects virtual-keyboard / pinch-zoom, so it wins over
    // the window's innerWidth/innerHeight when available.
    patchWithCleanup(browser, {
        visualViewport: /** @type {any} */ ({ width: 812, height: 543 }),
        innerWidth: 1000,
        innerHeight: 700,
    });
    expect(getViewportDimensions()).toEqual({ width: 812, height: 543 });
});

test("getViewportDimensions: falls back to innerWidth/innerHeight without visualViewport", () => {
    // Older browsers / embedded webviews expose no visualViewport — the ??
    // fallback must use the window dimensions rather than yield undefined.
    patchWithCleanup(browser, {
        visualViewport: /** @type {any} */ (undefined),
        innerWidth: 1024,
        innerHeight: 768,
    });
    expect(getViewportDimensions()).toEqual({ width: 1024, height: 768 });
});

test("useViewportChange: fires on viewport change while mounted, stops after unmount", async () => {
    let calls = 0;
    /** @type {{ show: boolean }} */
    let parentState;

    class Child extends Component {
        static template = xml`<div class="child"/>`;
        static props = ["*"];
        setup() {
            useViewportChange(() => {
                calls++;
            });
        }
    }
    class Parent extends Component {
        static components = { Child };
        static template = xml`<Child t-if="state.show"/>`;
        static props = ["*"];
        setup() {
            this.state = useState({ show: true });
            parentState = this.state;
        }
    }

    await mountWithCleanup(Parent);

    await resize({ width: 640, height: 480 });
    await animationFrame();
    expect(calls).toBe(1);

    // Unmount the Child: onWillUnmount must remove the viewport listener.
    parentState.show = false;
    await animationFrame();
    const callsAtUnmount = calls;

    await resize({ width: 800, height: 600 });
    await animationFrame();
    // No further callback after the listener was cleaned up.
    expect(calls).toBe(callsAtUnmount);
});
