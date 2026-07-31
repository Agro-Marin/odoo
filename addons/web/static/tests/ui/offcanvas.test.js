// @ts-check

import { beforeEach, disableAnimations, expect, test } from "@odoo/hoot";
import { click, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, useState, xml } from "@odoo/owl";
import { makeMockEnv, mountWithCleanup } from "@web/../tests/web_test_helpers";
import { Offcanvas } from "@web/ui/offcanvas/offcanvas";

beforeEach(async () => {
    disableAnimations();
    await makeMockEnv();
});

class Parent extends Component {
    static components = { Offcanvas };
    static props = ["*"];
    static template = xml`
        <button class="opener" t-on-click="() => this.state.open = true">Open</button>
        <Offcanvas
            open="state.open"
            placement="props.placement or 'end'"
            onClose="() => this.onClose()"
            class="'panel'"
        >
            <div class="body">content</div>
        </Offcanvas>
    `;

    setup() {
        this.state = useState({ open: false });
    }

    onClose() {
        this.state.open = false;
        expect.step("close");
    }
}

test("starts closed and is not in the top layer", async () => {
    await mountWithCleanup(Parent);

    expect(".panel").toHaveCount(1);
    expect(queryOne(".panel").matches(":popover-open")).toBe(false);
});

test("opens into the top layer and takes the show class", async () => {
    await mountWithCleanup(Parent);

    await click(".opener");
    await animationFrame();

    expect(queryOne(".panel").matches(":popover-open")).toBe(true);
    expect(".panel").toHaveClass("show");
});

// Escape and click-outside are the UA's own light-dismiss, and it only acts on
// trusted events — which the synthetic ones this harness dispatches are not.
// `hidePopover()` is the same path those dismissals end in, so it exercises the
// `toggle` wiring that has to survive a dismissal the component never asked for.
test("reports a dismissal it did not initiate through onClose", async () => {
    await mountWithCleanup(Parent);

    await click(".opener");
    await animationFrame();
    expect(queryOne(".panel").matches(":popover-open")).toBe(true);

    queryOne(".panel").hidePopover();
    await animationFrame();

    expect.verifySteps(["close"]);
    expect(queryOne(".panel").matches(":popover-open")).toBe(false);
    expect(".panel").not.toHaveClass("show");
});

test("applies the placement class", async () => {
    await mountWithCleanup(Parent, { props: { placement: "start" } });

    expect(".panel").toHaveClass("offcanvas-start");
    expect(".panel").not.toHaveClass("offcanvas-end");
});
