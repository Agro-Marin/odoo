// @ts-check

import { destroy, expect, getFixture, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import {
    contains,
    getService,
    mountWithCleanup,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { MainComponentsContainer } from "@web/ui/main_components_container";
import { makePopover, usePopover } from "@web/ui/popover/popover_hook";

test("close popover when component is unmounted", async () => {
    const target = getFixture();
    class Comp extends Component {
        static template = xml`<div t-att-id="props.id">in popover</div>`;
        static props = ["*"];
    }

    class CompWithPopover extends Component {
        static template = xml`<div />`;
        static props = ["*"];
        setup() {
            this.popover = usePopover(Comp);
        }
    }

    const comp1 = await mountWithCleanup(CompWithPopover);
    comp1.popover.open(target, { id: "comp1" });
    await animationFrame();

    const comp2 = await mountWithCleanup(CompWithPopover, { noMainContainer: true });
    comp2.popover.open(target, { id: "comp2" });
    await animationFrame();

    expect(".o_popover").toHaveCount(2);
    expect(".o_popover #comp1").toHaveCount(1);
    expect(".o_popover #comp2").toHaveCount(1);

    destroy(comp1);
    await animationFrame();

    expect(".o_popover").toHaveCount(1);
    expect(".o_popover #comp1").toHaveCount(0);
    expect(".o_popover #comp2").toHaveCount(1);

    destroy(comp2);
    await animationFrame();

    expect(".o_popover").toHaveCount(0);
    expect(".o_popover #comp1").toHaveCount(0);
    expect(".o_popover #comp2").toHaveCount(0);
});

test("popover opened from another", async () => {
    class Comp extends Component {
        static id = 0;
        static template = xml`
            <div class="p-4">
                <button class="pop-open" t-on-click="(ev) => this.popover.open(ev.target, {})">open popover</button>
            </div>
        `;
        static props = ["*"];
        setup() {
            this.popover = usePopover(Comp, {
                class: `popover-${++Comp.id}`,
            });
        }
    }

    await mountWithCleanup(Comp);

    await contains(".pop-open").click();
    expect(".popover-1").toHaveCount(1);

    await contains(".popover-1 .pop-open").click();
    expect(".o_popover").toHaveCount(2);
    expect(".popover-1").toHaveCount(1);
    expect(".popover-2").toHaveCount(1);

    await contains(".popover-2 .pop-open").click();
    expect(".o_popover").toHaveCount(3);
    expect(".popover-1").toHaveCount(1);
    expect(".popover-2").toHaveCount(1);
    expect(".popover-3").toHaveCount(1);

    await contains(".popover-3").click();
    expect(".o_popover").toHaveCount(3);
    expect(".popover-1").toHaveCount(1);
    expect(".popover-2").toHaveCount(1);
    expect(".popover-3").toHaveCount(1);

    await contains(".popover-2").click();
    expect(".o_popover").toHaveCount(2);
    expect(".popover-1").toHaveCount(1);
    expect(".popover-2").toHaveCount(1);

    await contains(document.body).click();
    expect(".o_popover").toHaveCount(0);
});

test("a hosted component's close reason reaches onClose", async () => {
    await mountWithCleanup(MainComponentsContainer);
    let received = "NEVER CALLED";
    class Closer extends Component {
        static template = xml`<div id="comp">in popover</div>`;
        static props = ["*"];
        setup() {
            this.props.close({ reason: "picked" });
        }
    }

    const popover = makePopover(getService("popover").add, Closer, {
        onClose: (params) => (received = params),
    });
    popover.open(getFixture(), {});
    await animationFrame();
    await animationFrame();
    expect(received).toEqual({ reason: "picked" });
});

test("the owner's own close reason reaches onClose", async () => {
    await mountWithCleanup(MainComponentsContainer);
    let received = "NEVER CALLED";
    class Comp extends Component {
        static template = xml`<div id="comp">in popover</div>`;
        static props = ["*"];
    }

    const popover = makePopover(getService("popover").add, Comp, {
        onClose: (params) => (received = params),
    });
    popover.open(getFixture(), {});
    await animationFrame();
    popover.close({ reason: "owner" });
    await animationFrame();
    await animationFrame();
    expect(received).toEqual({ reason: "owner" });
});

test("an unknown option still warns through the hook's option bag", async () => {
    await mountWithCleanup(MainComponentsContainer);
    class Comp extends Component {
        static template = xml`<div id="comp">in popover</div>`;
        static props = ["*"];
    }

    const warnings = [];
    patchWithCleanup(console, {
        warn: (...args) => warnings.push(args.join(" ")),
    });
    patchWithCleanup(odoo, { debug: "1" });

    const popover = makePopover(getService("popover").add, Comp, {
        totallyBogusOption: true,
    });
    popover.open(getFixture(), {});
    await animationFrame();

    expect(warnings.filter((w) => w.includes("totallyBogusOption"))).toHaveLength(1);
});
