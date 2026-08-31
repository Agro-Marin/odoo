import { addBuilderOption, setupHTMLBuilder } from "@html_builder/../tests/helpers";
import { BaseOptionComponent } from "@html_builder/core/utils";
import { expect, test, describe } from "@odoo/hoot";
import { xml } from "@odoo/owl";
import { contains } from "@web/../tests/web_test_helpers";
import { animationFrame } from "@odoo/hoot-dom";

describe.current.tags("desktop");

function addRowOption(selector, label) {
    addBuilderOption(
        class extends BaseOptionComponent {
            static selector = selector;
            static template = xml`<BuilderRow label="'${label}'">A</BuilderRow>`;
        }
    );
}

test("hovering an element with options outlines it", async () => {
    addRowOption("section", "Section");
    await setupHTMLBuilder(`
        <section style="height: 200px">
            <div class="inner">TEST</div>
        </section>`);

    expect(".oe_overlay.o_hover_overlay").toHaveCount(0);
    // The outline is throttled to one animation frame.
    await contains(":iframe section").hover();
    await animationFrame();
    expect(".oe_overlay.o_hover_overlay").toHaveCount(1);
    expect(".oe_overlay.o_hover_overlay").toHaveRect(":iframe section");
});

test("the outline follows the closest element that has options", async () => {
    addRowOption("section", "Section");
    addRowOption(".inner", "Inner");
    await setupHTMLBuilder(`
        <section style="height: 200px">
            <div class="inner" style="height: 50px">TEST</div>
        </section>`);

    await contains(":iframe section").hover();
    await animationFrame();
    expect(".oe_overlay.o_hover_overlay").toHaveRect(":iframe section");

    await contains(":iframe .inner").hover();
    await animationFrame();
    expect(".oe_overlay.o_hover_overlay").toHaveCount(1);
    expect(".oe_overlay.o_hover_overlay").toHaveRect(":iframe .inner");
});
