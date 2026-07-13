// @ts-check

import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import { mountWithCleanup, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { BottomSheet } from "@web/ui/bottom_sheet/bottom_sheet";

test("hardware Back pressed while dismissing consumes the synthetic history entry", async () => {
    // Count real history.back() calls. onMounted pushes ONE synthetic entry; the
    // sheet must never pop more than the browser already popped for us.
    let backCalls = 0;
    const originalBack = browser.history.back.bind(browser.history);
    patchWithCleanup(browser.history, {
        back() {
            backCalls++;
            originalBack(); // dispatches popstate, like the real browser
        },
    });

    class Child extends Component {
        static template = xml`<div class="sheet-child"/>`;
        static props = ["*"];
    }

    // No-op close so the component stays mounted while we inspect its state
    // (mimics the ~300ms close-animation window before unmount).
    const sheet = await mountWithCleanup(BottomSheet, {
        props: { component: Child, close: () => {} },
    });
    await animationFrame();

    // The sheet trapped the mobile Back gesture with a single synthetic entry.
    expect(sheet._historyStatePushed).toBe(true);

    // Close via escape/backdrop/close(): isDismissing flips true, animation runs.
    sheet.slideOut();
    expect(sheet.state.isDismissing).toBe(true);

    // Mid-animation the user presses hardware Back: the browser pops our synthetic
    // entry (backCalls === 1) and fires popstate. handlePopState must mark the
    // entry consumed EVEN while dismissing, otherwise onWillUnmount would later
    // call history.back() again and pop a real page entry, navigating away.
    browser.history.back();
    expect(backCalls).toBe(1);
    expect(sheet._historyStatePushed).toBe(false);
});
