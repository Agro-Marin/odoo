// @ts-check

import { beforeEach, expect, test } from "@odoo/hoot";
import { click } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import { makeMockEnv, mountWithCleanup } from "@web/../tests/web_test_helpers";

beforeEach(makeMockEnv);

class Parent extends Component {
    static props = ["*"];
    static template = xml`
        <div class="alert alert-info kept">
            <span>Untouched</span>
            <button class="btn-close other" aria-label="Close"/>
        </div>
        <div class="alert alert-danger removable">
            <span>Dismiss me</span>
            <a class="close trigger" data-dismiss-alert="1" href="#">x</a>
        </div>
    `;
}

test("clicking a data-dismiss-alert trigger removes its own alert", async () => {
    await mountWithCleanup(Parent);
    expect(".alert").toHaveCount(2);

    await click(".trigger");
    await animationFrame();

    expect(".removable").toHaveCount(0);
    expect(".kept").toHaveCount(1);
});

test("a close button without the marker leaves the alert alone", async () => {
    await mountWithCleanup(Parent);

    await click(".other");
    await animationFrame();

    expect(".alert").toHaveCount(2);
});
