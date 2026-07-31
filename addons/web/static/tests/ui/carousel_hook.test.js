// @ts-check

import { beforeEach, expect, test } from "@odoo/hoot";
import { click } from "@odoo/hoot-dom";
import { advanceTime, animationFrame } from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import { makeMockEnv, mountWithCleanup } from "@web/../tests/web_test_helpers";
import { useCarousel } from "@web/ui/carousel/carousel_hook";

beforeEach(makeMockEnv);

function makeParent(params = {}) {
    class Parent extends Component {
        static props = ["*"];
        static template = xml`
            <div class="carousel slide carousel-fade">
                <div class="carousel-inner">
                    <t t-foreach="slides" t-as="slide" t-key="slide">
                        <div t-attf-class="carousel-item item-{{slide}}"
                             t-att-class="{active: carousel.state.index === slide_index}"/>
                    </t>
                </div>
                <button class="prev" t-on-click="() => this.carousel.previous()">P</button>
                <button class="next" t-on-click="() => this.carousel.next()">N</button>
                <button class="last" t-on-click="() => this.carousel.goTo(2)">L</button>
            </div>
        `;

        /** @type {string[]} */
        slides;
        /** @type {ReturnType<typeof useCarousel>} */
        carousel;

        setup() {
            this.slides = ["a", "b", "c"];
            this.carousel = useCarousel({ count: () => this.slides.length, ...params });
        }
    }
    return Parent;
}

test("marks the first slide active by default", async () => {
    await mountWithCleanup(makeParent());

    expect(".item-a").toHaveClass("active");
    expect(".item-b").not.toHaveClass("active");
});

test("advances and goes back", async () => {
    await mountWithCleanup(makeParent());

    await click(".next");
    await animationFrame();
    expect(".item-b").toHaveClass("active");

    await click(".prev");
    await animationFrame();
    expect(".item-a").toHaveClass("active");
});

test("wraps around both ends by default", async () => {
    await mountWithCleanup(makeParent());

    await click(".prev");
    await animationFrame();
    expect(".item-c").toHaveClass("active");

    await click(".next");
    await animationFrame();
    expect(".item-a").toHaveClass("active");
});

test("clamps instead of wrapping when wrap is false", async () => {
    await mountWithCleanup(makeParent({ wrap: false }));

    await click(".prev");
    await animationFrame();
    expect(".item-a").toHaveClass("active");

    await click(".last");
    await click(".next");
    await animationFrame();
    expect(".item-c").toHaveClass("active");
});

test("jumps to an arbitrary slide", async () => {
    await mountWithCleanup(makeParent());

    await click(".last");
    await animationFrame();
    expect(".item-c").toHaveClass("active");
});

test("autoplays on an interval and stops once destroyed", async () => {
    await mountWithCleanup(makeParent({ interval: 1000 }));

    await advanceTime(1000);
    await animationFrame();
    expect(".item-b").toHaveClass("active");

    await advanceTime(1000);
    await animationFrame();
    expect(".item-c").toHaveClass("active");
});
