// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { press, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, onWillRender, useState, xml } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { AppEvent } from "@web/core/events";
import { useAutofocus, useService } from "@web/core/utils/hooks";
import { MainComponentsContainer } from "@web/ui/main_components_container";
import { useActiveElement } from "@web/ui/ui_service";
import { SIZES } from "@web/ui/viewport";

import {
    getService,
    makeMockEnv,
    mountWithCleanup,
    patchWithCleanup,
} from "../web_test_helpers.js";

describe.current.tags("desktop");

test("block and unblock once ui with ui service", async () => {
    await mountWithCleanup(MainComponentsContainer);
    expect(".o_blockUI").toHaveCount(0);
    getService("ui").block();
    await animationFrame();
    expect(".o_blockUI").toHaveCount(1);
    getService("ui").unblock();
    await animationFrame();
    expect(".o_blockUI").toHaveCount(0);
});

test("use block and unblock several times to block ui with ui service", async () => {
    await mountWithCleanup(MainComponentsContainer);
    expect(".o_blockUI").toHaveCount(0);
    getService("ui").block();
    getService("ui").block();
    getService("ui").block();
    await animationFrame();
    expect(".o_blockUI").toHaveCount(1);
    getService("ui").unblock();
    getService("ui").unblock();
    await animationFrame();
    expect(".o_blockUI").toHaveCount(1);
    getService("ui").unblock();
    await animationFrame();
    expect(".o_blockUI").toHaveCount(0);
});

test("isBlocked and activeElement are reactive properties", async () => {
    class MyComponent extends Component {
        static template = xml`
            <div>
                <span class="blocked" t-esc="ui.isBlocked"/>
                <span class="active" t-esc="isDocumentActive ? 'document' : 'other'"/>
                <div t-if="hasRef" id="owner" t-ref="delegatedRef">
                    <input type="text"/>
                </div>
            </div>
        `;
        static props = ["*"];
        setup() {
            this.ui = useState(useService("ui"));
            useActiveElement("delegatedRef");
            this.hasRef = true;
        }
        get isDocumentActive() {
            return this.ui.activeElement === document;
        }
    }

    const comp = await mountWithCleanup(MyComponent);
    expect(".blocked").toHaveText("false");
    expect(".active").toHaveText("other");

    getService("ui").block();
    await animationFrame();
    expect(".blocked").toHaveText("true");
    expect(getService("ui").isBlocked).toBe(true);
    getService("ui").unblock();
    await animationFrame();
    expect(".blocked").toHaveText("false");
    expect(getService("ui").isBlocked).toBe(false);

    comp.hasRef = false;
    comp.render();
    await animationFrame();
    await animationFrame();
    expect(".active").toHaveText("document");
});

test("a component can be the  UI active element: simple usage", async () => {
    class MyComponent extends Component {
        static template = xml`
            <div>
                <h1>My Component</h1>
                <div t-if="hasRef" id="owner" t-ref="delegatedRef">
                <input type="text"/>
            </div>
            </div>
        `;
        static props = ["*"];
        setup() {
            useActiveElement("delegatedRef");
            this.hasRef = true;
        }
    }

    const comp = await mountWithCleanup(MyComponent);

    expect(/** @type {any} */ (getService("ui").activeElement)).toBe(
        queryOne("#owner"),
    );
    expect("#owner input").toBeFocused();
    comp.hasRef = false;
    comp.render();
    await animationFrame();
    expect(/** @type {any} */ (getService("ui").activeElement)).toBe(document);
    expect(document.body).toBeFocused();
});

test("UI active element: trap focus", async () => {
    class MyComponent extends Component {
        static template = xml`
            <div>
                <h1>My Component</h1>
                <input type="text" placeholder="outerUIActiveElement"/>
                <div t-ref="delegatedRef">
                    <input type="text" placeholder="withFocus"/>
                </div>
            </div>
        `;
        static props = ["*"];
        setup() {
            useActiveElement("delegatedRef");
        }
    }

    await mountWithCleanup(MyComponent);

    expect("input[placeholder=withFocus]").toBeFocused();
    let [firstEvent] = await press("Tab", { shiftKey: false });
    await animationFrame();
    expect(firstEvent.defaultPrevented).toBe(true);
    expect("input[placeholder=withFocus]").toBeFocused();

    [firstEvent] = await press("Tab", { shiftKey: true });
    await animationFrame();
    expect(firstEvent.defaultPrevented).toBe(true);
    expect("input[placeholder=withFocus]").toBeFocused();
});

test("UI active element: trap focus - default focus with autofocus", async () => {
    class MyComponent extends Component {
        static template = xml`
            <div>
                <h1>My Component</h1>
                <input type="text" placeholder="outerUIActiveElement"/>
                <div t-ref="delegatedRef">
                    <input type="text" placeholder="withoutFocus"/>
                    <input type="text" t-ref="autofocus" placeholder="withAutoFocus"/>
                </div>
            </div>
        `;
        static props = ["*"];
        setup() {
            useActiveElement("delegatedRef");
            useAutofocus();
        }
    }

    await mountWithCleanup(MyComponent);

    expect("input[placeholder=withAutoFocus]").toBeFocused();
    let [firstEvent] = await press("Tab", { shiftKey: false });
    await animationFrame();
    expect(firstEvent.defaultPrevented).toBe(true);
    expect("input[placeholder=withoutFocus]").toBeFocused();

    [firstEvent] = await press("Tab", { shiftKey: true });
    await animationFrame();
    expect(firstEvent.defaultPrevented).toBe(true);
    expect("input[placeholder=withAutoFocus]").toBeFocused();

    [firstEvent] = await press("Tab", { shiftKey: true });
    await animationFrame();
    expect(firstEvent.defaultPrevented).toBe(false);
});

test("do not become UI active element if no element to focus", async () => {
    class MyComponent extends Component {
        static template = xml`
            <div>
                <h1>My Component</h1>
                <input type="text" placeholder="outerUIActiveElement"/>
                <div id="idActiveElement" t-ref="delegatedRef">
                    <div>
                        <span> No focus element </span>
                    </div>
                </div>
            </div>
        `;
        static props = ["*"];
        setup() {
            useActiveElement("delegatedRef");
        }
    }

    await mountWithCleanup(MyComponent);
    expect(/** @type {any} */ (getService("ui").activeElement)).toBe(document);
});

test("become UI active element if no element to focus but the container is focusable", async () => {
    class MyComponent extends Component {
        static template = xml`
            <div>
                <h1>My Component</h1>
                <input type="text" placeholder="outerUIActiveElement"/>
                <div id="idActiveElement" t-ref="delegatedRef" tabindex="-1">
                    <div>
                        <span> No focus element </span>
                    </div>
                </div>
            </div>
        `;
        static props = ["*"];
        setup() {
            useActiveElement("delegatedRef");
        }
    }

    await mountWithCleanup(MyComponent);
    expect(/** @type {any} */ (getService("ui").activeElement)).toBe(
        queryOne("#idActiveElement"),
    );
});

test("UI active element: trap focus - first or last tabable changes", async () => {
    class MyComponent extends Component {
        static template = xml`
            <div>
                <h1>My Component</h1>
                <input type="text" name="outer"/>
                <div id="idActiveElement" t-ref="delegatedRef">
                    <div>
                        <input type="text" name="a" t-if="show.a"/>
                        <input type="text" name="b"/>
                        <input type="text" name="c" t-if="show.c"/>
                    </div>
                </div>
            </div>
        `;
        static props = ["*"];
        setup() {
            this.show = useState({ a: true, c: false });
            useActiveElement("delegatedRef");
        }
    }

    const comp = await mountWithCleanup(MyComponent);

    expect("input[name=a]").toBeFocused();

    let [firstEvent] = await press("Tab", { shiftKey: true });
    await animationFrame();
    expect(firstEvent.defaultPrevented).toBe(true);
    expect("input[name=b]").toBeFocused();

    comp.show.a = false;
    comp.show.c = true;
    await animationFrame();
    expect("input[name=b]").toBeFocused();

    [firstEvent] = await press("Tab", { shiftKey: true });
    await animationFrame();
    expect(firstEvent.defaultPrevented).toBe(true);
    expect("input[name=c]").toBeFocused();
});

test("UI active element: trap focus is not bypassed using invisible elements", async () => {
    class MyComponent extends Component {
        static template = xml`
            <div>
                <h1>My Component</h1>
                <input type="text" placeholder="outerUIActiveElement"/>
                <div t-ref="delegatedRef">
                    <input type="text" placeholder="withFocus"/>
                    <input class="d-none" type="text" placeholder="withFocusNotDisplayed"/>
                    <div class="d-none">
                        <input type="text" placeholder="withFocusNotDisplayedToo"/>
                    </div>
                </div>
            </div>
        `;
        static props = ["*"];
        setup() {
            useActiveElement("delegatedRef");
        }
    }

    await mountWithCleanup(MyComponent);

    expect("input[placeholder=withFocus]").toBeFocused();

    let [firstEvent] = await press("Tab", { shiftKey: false });
    await animationFrame();
    expect(firstEvent.defaultPrevented).toBe(true);
    expect("input[placeholder=withFocus]").toBeFocused();

    [firstEvent] = await press("Tab", { shiftKey: true });
    await animationFrame();
    expect(firstEvent.defaultPrevented).toBe(true);
    expect("input[placeholder=withFocus]").toBeFocused();
});

test("the service releases its breakpoint listeners on destroy", async () => {
    await makeMockEnv();

    let attached = 0;
    patchWithCleanup(browser, {
        matchMedia: (/** @type {string} */ query) => {
            const isBreakpoint = query.startsWith("(min-width:");
            return {
                matches: false,
                addEventListener() {
                    if (isBreakpoint) {
                        attached++;
                    }
                },
                removeEventListener() {
                    if (isBreakpoint) {
                        attached--;
                    }
                },
            };
        },
    });

    const env = await makeMockEnv();
    expect(attached).toBe(SIZES.XXL);

    /** @type {any} */ (env.services.ui).destroy();
    expect(attached).toBe(0);
});

test("each env blocks its own container, not its neighbour's", async () => {
    const envA = await makeMockEnv();
    const envB = await makeMockEnv(undefined, { makeNew: true });
    expect(envA.services.ui).not.toBe(envB.services.ui);

    await mountWithCleanup(MainComponentsContainer, { env: envB });
    expect(".o_blockUI").toHaveCount(0);

    envB.services.ui.block();
    await animationFrame();
    expect(".o_blockUI").toHaveCount(1);
    envB.services.ui.unblock();
    await animationFrame();
    expect(".o_blockUI").toHaveCount(0);

    envA.services.ui.block();
    await animationFrame();
    expect(".o_blockUI").toHaveCount(0);
    envA.services.ui.unblock();
    await animationFrame();
});

test("the blocking overlay announces its message politely", async () => {
    await mountWithCleanup(MainComponentsContainer);
    getService("ui").block();
    await animationFrame();

    expect(".o_blockUI .o_message").toHaveAttribute("role", "status");
    expect(".o_blockUI .o_message").toHaveAttribute("aria-live", "polite");
    expect(".o_blockUI .o_spinner img").toHaveAttribute("alt", "");

    getService("ui").unblock();
    await animationFrame();
});

/**
 * @param {() => number} getWidth
 */
function mockMatchMediaAtWidth(getWidth) {
    /** @type {any[]} */
    const medias = [];
    patchWithCleanup(browser, {
        matchMedia: (/** @type {string} */ query) => {
            const min = query.match(/min-width:\s*([\d.]+)px/)?.[1];
            const max = query.match(/max-width:\s*([\d.]+)px/)?.[1];
            /** @type {any[]} */
            const listeners = [];
            const media = {
                get matches() {
                    if (min === undefined && max === undefined) {
                        return false;
                    }
                    const width = getWidth();
                    return (
                        (min === undefined || width >= Number(min)) &&
                        (max === undefined || width <= Number(max))
                    );
                },
                addEventListener: (/** @type {any} */ _, /** @type {any} */ cb) =>
                    listeners.push(cb),
                removeEventListener: () => {},
                notify: () =>
                    listeners.forEach((cb) =>
                        cb({ matches: media.matches, target: media }),
                    ),
            };
            medias.push(media);
            return media;
        },
    });
    return { notifyAll: () => medias.forEach((m) => m.notify()) };
}

test("every viewport width maps to a size, including between breakpoints", async () => {
    for (const width of [575.5, 767.5, 991.5, 1199.5, 1399.5]) {
        mockMatchMediaAtWidth(() => width);
        const env = await makeMockEnv(undefined, { makeNew: true });
        const ui = /** @type {any} */ (env.services.ui);
        expect(ui.size).toBeWithin(SIZES.XS, SIZES.XXL + 1);
        expect(Number.isInteger(ui.size)).toBe(true);
        expect(ui.isSmall).toBe(ui.size <= SIZES.SM);
    }
});

test("the size at a boundary width is the band that starts there", async () => {
    for (const [width, expected] of [
        [575, SIZES.XS],
        [576, SIZES.SM],
        [767, SIZES.SM],
        [768, SIZES.MD],
        [1399, SIZES.XL],
        [1400, SIZES.XXL],
    ]) {
        mockMatchMediaAtWidth(() => width);
        const env = await makeMockEnv(undefined, { makeNew: true });
        expect(/** @type {any} */ (env.services.ui).size).toBe(expected);
    }
});

test("a resize that does not change the size does not broadcast", async () => {
    let width = 1000;
    const { notifyAll } = mockMatchMediaAtWidth(() => width);
    const env = await makeMockEnv(undefined, { makeNew: true });
    const ui = /** @type {any} */ (env.services.ui);
    ui.bus.addEventListener(AppEvent.RESIZE, () => expect.step("resize"));
    expect(ui.size).toBe(SIZES.LG);

    width = 1100;
    notifyAll();
    expect.verifySteps([]);
    expect(ui.size).toBe(SIZES.LG);

    width = 1300;
    notifyAll();
    expect.verifySteps(["resize"]);
    expect(ui.size).toBe(SIZES.XL);
});

test("an element activated twice stays active after one deactivation", async () => {
    const env = await makeMockEnv();
    const ui = env.services.ui;
    const host = document.createElement("div");
    const overlay = document.createElement("div");
    document.body.append(host, overlay);

    ui.activateElement(host);
    ui.activateElement(overlay);
    ui.activateElement(host);
    ui.deactivateElement(overlay);
    ui.deactivateElement(host);

    expect(ui.activeElement).toBe(host);

    ui.deactivateElement(host);
    expect(ui.activeElement).toBe(document);
    host.remove();
    overlay.remove();
});

test("deactivating an element that was never activated is a no-op", async () => {
    const env = await makeMockEnv();
    const ui = env.services.ui;
    const stranger = document.createElement("div");

    ui.deactivateElement(stranger);
    expect(ui.activeElement).toBe(document);
});

test("destroy() releases the active-element stack and the block counter", async () => {
    const env = await makeMockEnv();
    const ui = env.services.ui;
    const el = document.createElement("div");
    document.body.append(el);
    ui.activateElement(el);
    ui.block();
    expect(ui.activeElement).toBe(el);
    expect(ui.isBlocked).toBe(true);

    ui.destroy();

    expect(ui.activeElement).toBe(document);
    expect(ui.isBlocked).toBe(false);
    el.remove();
});

test("an unmatched unblock leaves the ui unblocked and announces nothing", async () => {
    const env = await makeMockEnv();
    const ui = /** @type {any} */ (env.services.ui);
    patchWithCleanup(console, { warn: () => expect.step("warn") });
    ui.bus.addEventListener(AppEvent.UNBLOCK, () => expect.step("unblock"));

    ui.unblock();

    expect(ui.blockCount).toBe(0);
    expect(ui.isBlocked).toBe(false);
    expect.verifySteps(["warn"]);

    ui.block();
    expect(ui.isBlocked).toBe(true);
    ui.unblock();
    expect(ui.isBlocked).toBe(false);
    expect.verifySteps(["unblock"]);
});

test("isBlocked is its own reactive key, so a nested block does not invalidate it", async () => {
    class Reader extends Component {
        static template = xml`<div class="reader" t-esc="ui.isBlocked"/>`;
        static props = {};
        setup() {
            this.ui = useState(useService("ui"));
            onWillRender(() => expect.step(`render ${this.ui.isBlocked}`));
        }
    }
    await mountWithCleanup(Reader);
    expect.verifySteps(["render false"]);

    const ui = /** @type {any} */ (getService("ui"));
    ui.block();
    await animationFrame();
    expect.verifySteps(["render true"]);

    ui.block();
    ui.block();
    await animationFrame();
    expect(ui.blockCount).toBe(3);
    expect.verifySteps([]);

    ui.unblock();
    ui.unblock();
    await animationFrame();
    expect(ui.isBlocked).toBe(true);
    expect.verifySteps([]);

    ui.unblock();
    await animationFrame();
    expect.verifySteps(["render false"]);
});
