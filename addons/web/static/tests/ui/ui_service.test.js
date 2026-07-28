// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { press, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, useState, xml } from "@odoo/owl";
import { MainComponentsContainer } from "@web/components/main_components_container";
import { useAutofocus, useService } from "@web/core/utils/hooks";
import { useActiveElement } from "@web/ui/ui_service";
import { MEDIAS_BREAKPOINTS } from "@web/ui/viewport";

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

// REGRESSION-BLOCK
test("the service releases its breakpoint listeners on destroy", async () => {
    // A first env makes sure `MEDIAS` is already bound, so the next start
    // rebuilds it from the patched `matchMedia` below.
    await makeMockEnv();

    let attached = 0;
    patchWithCleanup(window, {
        matchMedia: () => ({
            matches: false,
            addEventListener: () => attached++,
            removeEventListener: () => attached--,
        }),
    });

    const env = await makeMockEnv();
    expect(attached).toBe(MEDIAS_BREAKPOINTS.length);

    /** @type {any} */ (env.services.ui).destroy();
    expect(attached).toBe(0);
});

// BLOCKUI-A11Y-BLOCK
test("the blocking overlay announces its message politely", async () => {
    await mountWithCleanup(MainComponentsContainer);
    getService("ui").block();
    await animationFrame();

    expect(".o_blockUI .o_message").toHaveAttribute("role", "status");
    expect(".o_blockUI .o_message").toHaveAttribute("aria-live", "polite");
    // The spinner is decorative: the live region already carries the text.
    expect(".o_blockUI .o_spinner img").toHaveAttribute("alt", "");

    getService("ui").unblock();
    await animationFrame();
});
