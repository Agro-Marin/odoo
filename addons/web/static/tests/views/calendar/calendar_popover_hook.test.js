// @ts-check

import { expect, test } from "@odoo/hoot";
import { animationFrame, click } from "@odoo/hoot-dom";
import { Component, xml } from "@odoo/owl";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { useCalendarPopover } from "@web/views/calendar/hooks/calendar_popover_hook";

class Content extends Component {
    static template = xml`<div class="o_probe_content">popover</div>`;
    static props = ["*"];
}

class Host extends Component {
    static template = xml`<button class="o_probe_target" t-on-click="open">open</button>`;
    static props = ["*"];
    setup() {
        this.popover = useCalendarPopover(Content);
    }
    open(ev) {
        this.popover.open(ev.target, {}, "o_probe_class");
    }
}

async function mountHost() {
    const host = await mountWithCleanup(Host);
    expect(host.popover.isOpen).toBe(false);
    await click(".o_probe_target");
    await animationFrame();
    expect(".o_probe_content").toHaveCount(1);
    expect(host.popover.isOpen).toBe(true);
    host.popover.close();
    await animationFrame();
    expect(".o_probe_content").toHaveCount(0);
    expect(host.popover.isOpen).toBe(false);
}

test.tags("desktop");
test("isOpen follows the popover", async () => {
    await mountHost();
    expect(".o-overlay-container .modal").toHaveCount(0);
});

test.tags("mobile");
test("isOpen follows the dialog on a small screen", async () => {
    await mountHost();
    expect(".o_popover").toHaveCount(0);
});
