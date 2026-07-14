import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { useHover } from "@mail/utils/common/hooks";
import { describe, expect, test } from "@odoo/hoot";
import { animationFrame, hover, leave, runAllTimers } from "@odoo/hoot-dom";
import { Component, useState, xml } from "@odoo/owl";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineMailModels();

test("useHover cancels its pending timers on unmount", async () => {
    class HoverTarget extends Component {
        static props = [];
        static template = xml`<div class="test-hover" t-ref="root">hover me</div>`;

        setup() {
            this.hover = useHover("root", {
                onAway: () => expect.step("away"),
                onHovering: [5000, () => expect.step("hovering")],
            });
        }
    }
    class Parent extends Component {
        static components = { HoverTarget };
        static props = [];
        static template = xml`<HoverTarget t-if="state.mounted"/>`;

        setup() {
            this.state = useState({ mounted: true });
        }
    }
    const parent = await mountWithCleanup(Parent);
    await hover(".test-hover");
    // leaving schedules the delayed onAway callback (and onHovering is still
    // pending from the hover)
    await leave();
    parent.state.mounted = false;
    await animationFrame();
    await runAllTimers();
    // no callback may fire against the destroyed component
    expect.verifySteps([]);
});
