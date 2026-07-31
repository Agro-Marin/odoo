// @ts-check

import { beforeEach, disableAnimations, expect, test } from "@odoo/hoot";
import { click } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, useState, xml } from "@odoo/owl";
import { makeMockEnv, mountWithCleanup } from "@web/../tests/web_test_helpers";
import { Collapse } from "@web/ui/collapse/collapse";

beforeEach(async () => {
    disableAnimations();
    await makeMockEnv();
});

class Parent extends Component {
    static components = { Collapse };
    static props = ["*"];
    static template = xml`
        <button class="toggle" t-on-click="() => this.state.open = !this.state.open">Toggle</button>
        <Collapse open="state.open" class="'region'">
            <div class="content">body</div>
        </Collapse>
    `;

    setup() {
        this.state = useState({ open: this.props.open ?? false });
    }
}

test("starts closed", async () => {
    await mountWithCleanup(Parent);

    expect(".region").toHaveClass("collapse");
    expect(".region").not.toHaveClass("show");
    expect(".region").not.toHaveClass("collapsing");
});

test("starts open without playing the opening animation", async () => {
    await mountWithCleanup(Parent, { props: { open: true } });
    await animationFrame();

    expect(".region").toHaveClass("collapse");
    expect(".region").toHaveClass("show");
});

test("opens and closes on toggle", async () => {
    await mountWithCleanup(Parent);

    await click(".toggle");
    await animationFrame();
    expect(".region").toHaveClass("show");
    expect(".region").not.toHaveClass("collapsing");

    await click(".toggle");
    await animationFrame();
    expect(".region").not.toHaveClass("show");
    expect(".region").toHaveClass("collapse");
});

test("leaves no inline sizing behind once settled", async () => {
    await mountWithCleanup(Parent);

    await click(".toggle");
    await animationFrame();

    expect(".region").toHaveAttribute("style", "");
});

test("keeps the slot content mounted while closed", async () => {
    await mountWithCleanup(Parent);

    expect(".content").toHaveCount(1);
});
