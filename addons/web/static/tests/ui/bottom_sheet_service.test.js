// @ts-check

import { afterEach, expect, getFixture, test } from "@odoo/hoot";
import { press } from "@odoo/hoot-dom";
import { animationFrame, runAllTimers } from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import { getService, mountWithCleanup } from "@web/../tests/web_test_helpers";
import { MainComponentsContainer } from "@web/components/main_components_container";

afterEach(() => {
    document.body.classList.remove("bottom-sheet-open", "bottom-sheet-open-multiple");
});

test("closing a bottom sheet decrements the count and clears the body class", async () => {
    await mountWithCleanup(MainComponentsContainer);

    class MyComp extends Component {
        static template = xml`<div class="sheet-content"/>`;
        static props = ["*"];
    }

    const close = getService("bottom_sheet").add(getFixture(), MyComp);
    await animationFrame();
    expect(document.body).toHaveClass("bottom-sheet-open");

    close();
    await animationFrame();
    expect(document.body).not.toHaveClass("bottom-sheet-open");

    close();
    await animationFrame();
    expect(document.body).not.toHaveClass("bottom-sheet-open");
});

test("a throwing onClose still decrements the count and clears the body class", async () => {
    expect.errors(1);
    await mountWithCleanup(MainComponentsContainer);

    class MyComp extends Component {
        static template = xml`<div class="sheet-content"/>`;
        static props = ["*"];
    }

    const close = getService("bottom_sheet").add(
        getFixture(),
        MyComp,
        {},
        {
            onClose: () => {
                throw new Error("onClose boom");
            },
        },
    );
    await animationFrame();
    expect(document.body).toHaveClass("bottom-sheet-open");

    close();
    await animationFrame();
    expect(document.body).not.toHaveClass("bottom-sheet-open");
    expect.verifyErrors(["Error: onClose boom"]);
});

test("a crashing bottom sheet subtree still decrements the count and clears the body class", async () => {
    expect.errors(1);
    await mountWithCleanup(MainComponentsContainer);

    class Boom extends Component {
        static template = xml``;
        static props = ["*"];
        setup() {
            throw new Error("bottom sheet crashed");
        }
    }

    getService("bottom_sheet").add(getFixture(), Boom);
    await animationFrame();

    expect(document.body).not.toHaveClass("bottom-sheet-open");
    expect.verifyErrors(["Error: bottom sheet crashed"]);
});

// OPTION-PARITY-BLOCK
// `usePopover` picks between the popover and the sheet from a live media
// query, so any option one backend honours and the other silently drops is an
// option whose meaning changes when the viewport crosses a breakpoint.
test.tags("mobile");
test("a sheet honours closeOnEscape, like the popover does", async () => {
    await mountWithCleanup(MainComponentsContainer);

    class MyComp extends Component {
        static template = xml`<div class="sheet-content"/>`;
        static props = ["*"];
    }

    getService("bottom_sheet").add(getFixture(), MyComp, {}, { closeOnEscape: false });
    await animationFrame();
    await animationFrame();
    expect(".sheet-content").toHaveCount(1);

    await press("escape");
    await runAllTimers();
    await animationFrame();
    expect(".sheet-content").toHaveCount(1);
});

test.tags("mobile");
test("a sheet closes on escape by default", async () => {
    await mountWithCleanup(MainComponentsContainer);

    class MyComp extends Component {
        static template = xml`<div class="sheet-content"/>`;
        static props = ["*"];
    }

    getService("bottom_sheet").add(getFixture(), MyComp);
    await animationFrame();
    await animationFrame();
    expect(".sheet-content").toHaveCount(1);

    await press("escape");
    await runAllTimers();
    await animationFrame();
    expect(".sheet-content").toHaveCount(0);
});
