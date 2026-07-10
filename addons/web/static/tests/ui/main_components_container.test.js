// @ts-check

import { beforeEach, expect, onError, test } from "@odoo/hoot";
import { animationFrame, Deferred } from "@odoo/hoot-mock";
import { Component, onWillStart, useState, xml } from "@odoo/owl";
import {
    clearRegistry,
    mountWithCleanup,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { MainComponentsContainer } from "@web/components/main_components_container";
import { registry } from "@web/core/registry";

const mainComponentsRegistry = registry.category("main_components");

beforeEach(async () => {
    clearRegistry(mainComponentsRegistry);
});

test("simple rendering", async () => {
    class MainComponentA extends Component {
        static template = xml`<span>MainComponentA</span>`;
        static props = ["*"];
    }

    class MainComponentB extends Component {
        static template = xml`<span>MainComponentB</span>`;
        static props = ["*"];
    }

    mainComponentsRegistry.add("MainComponentA", {
        Component: MainComponentA,
        props: {},
    });
    mainComponentsRegistry.add("MainComponentB", {
        Component: MainComponentB,
        props: {},
    });
    await mountWithCleanup(MainComponentsContainer);
    expect("div.o-main-components-container").toHaveCount(1);
    // ``clearRegistry`` can't unregister system-level main components other
    // modules attach (ChatHub, notification managers, etc.), so asserting
    // exact innerHTML would couple this test to the unit-test bundle's
    // contents. Verify just that OUR two registry entries render.
    expect(".o-main-components-container > span:first-child").toHaveText(
        "MainComponentA",
    );
    expect(".o-main-components-container > span:nth-child(2)").toHaveText(
        "MainComponentB",
    );
});

test("unmounts erroring main component", async () => {
    // Bumped from 6→7 after splitting the brittle ``toHaveInnerHTML``
    // root assertion into per-child ``toHaveText`` checks (see comment
    // below).
    expect.assertions(7);
    expect.errors(1);
    onError((error) => {
        expect.step(error.reason.message);
        expect.step(error.reason.cause.message);
    });
    let compA;
    class MainComponentA extends Component {
        static template = xml`<span><t t-if="state.shouldThrow" t-esc="error"/>MainComponentA</span>`;
        static props = ["*"];
        setup() {
            compA = this;
            this.state = useState({ shouldThrow: false });
        }
        get error() {
            throw new Error("BOOM");
        }
    }

    class MainComponentB extends Component {
        static template = xml`<span>MainComponentB</span>`;
        static props = ["*"];
    }

    mainComponentsRegistry.add("MainComponentA", {
        Component: MainComponentA,
        props: {},
    });
    mainComponentsRegistry.add("MainComponentB", {
        Component: MainComponentB,
        props: {},
    });
    await mountWithCleanup(MainComponentsContainer);
    expect("div.o-main-components-container").toHaveCount(1);
    // See ``simple rendering`` test for why exact-innerHTML assertions
    // are too brittle in this fork — verify the two TEST components are
    // present rather than asserting the full container contents.
    expect(".o-main-components-container > span:first-child").toHaveText(
        "MainComponentA",
    );
    expect(".o-main-components-container > span:nth-child(2)").toHaveText(
        "MainComponentB",
    );
    compA.state.shouldThrow = true;
    await animationFrame();
    expect.verifySteps([
        'An error occured in the owl lifecycle (see this Error\'s "cause" property)',
        "BOOM",
    ]);
    expect.verifyErrors(["BOOM"]);

    // After MainComponentA errors out, only MainComponentB is left as a
    // direct ``<span>`` child — system components render as ``<div>``s, so
    // the span count is still a safe discriminator.
    expect(".o-main-components-container > span").toHaveCount(1);
    expect(".o-main-components-container > span").toHaveText("MainComponentB");
});

test("unmounts erroring main component: variation", async () => {
    // See sibling test — assertion count bumped 6→7 for the same
    // split-into-two-children reason.
    expect.assertions(7);
    expect.errors(1);
    onError((error) => {
        expect.step(error.reason.message);
        expect.step(error.reason.cause.message);
    });
    class MainComponentA extends Component {
        static template = xml`<span>MainComponentA</span>`;
        static props = ["*"];
    }

    let compB;
    class MainComponentB extends Component {
        static template = xml`<span><t t-if="state.shouldThrow" t-esc="error"/>MainComponentB</span>`;
        static props = ["*"];
        setup() {
            compB = this;
            this.state = useState({ shouldThrow: false });
        }
        get error() {
            throw new Error("BOOM");
        }
    }

    mainComponentsRegistry.add("MainComponentA", {
        Component: MainComponentA,
        props: {},
    });
    mainComponentsRegistry.add("MainComponentB", {
        Component: MainComponentB,
        props: {},
    });
    await mountWithCleanup(MainComponentsContainer);
    expect("div.o-main-components-container").toHaveCount(1);
    // See ``simple rendering`` test above for the brittle-innerHTML
    // rationale: assert only on the two test components.
    expect(".o-main-components-container > span:first-child").toHaveText(
        "MainComponentA",
    );
    expect(".o-main-components-container > span:nth-child(2)").toHaveText(
        "MainComponentB",
    );
    compB.state.shouldThrow = true;
    await animationFrame();
    expect.verifySteps([
        'An error occured in the owl lifecycle (see this Error\'s "cause" property)',
        "BOOM",
    ]);
    expect.verifyErrors(["BOOM"]);
    expect(".o-main-components-container > span").toHaveCount(1);
    expect(".o-main-components-container > span").toHaveText("MainComponentA");
});

test("MainComponentsContainer re-renders when the registry changes", async () => {
    await mountWithCleanup(MainComponentsContainer);

    expect(".myMainComponent").toHaveCount(0);
    class MyMainComponent extends Component {
        static template = xml`<div class="myMainComponent" />`;
        static props = ["*"];
    }
    mainComponentsRegistry.add("myMainComponent", { Component: MyMainComponent });
    await animationFrame();
    expect(".myMainComponent").toHaveCount(1);
});

test("Should be possible to add a new component when MainComponentContainer is not mounted yet", async () => {
    const defer = new Deferred();
    patchWithCleanup(MainComponentsContainer.prototype, {
        setup() {
            super.setup();
            onWillStart(async () => {
                await defer;
            });
        },
    });
    mountWithCleanup(MainComponentsContainer);
    class MyMainComponent extends Component {
        static template = xml`<div class="myMainComponent" />`;
        static props = ["*"];
    }
    // Wait for the setup of MainComponentsContainer to be completed
    await animationFrame();
    mainComponentsRegistry.add("myMainComponent", { Component: MyMainComponent });
    // Release the component mounting
    defer.resolve();
    await animationFrame();
    expect(".myMainComponent").toHaveCount(1);
});
