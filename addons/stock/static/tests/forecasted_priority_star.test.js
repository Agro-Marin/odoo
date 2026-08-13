// @ts-check

import { describe, expect, getFixture, test } from "@odoo/hoot";

describe.current.tags("headless");

function mountStars() {
    const fixture = getFixture();
    fixture.innerHTML = `<div class="o_stock_forecasted_page">
        <span class="o_priority o_priority_star fa-regular fa-star" id="off"></span>
        <span class="o_priority o_priority_star fa-solid fa-star" id="on"></span>
    </div>`;
    return {
        off: fixture.querySelector("#off"),
        on: fixture.querySelector("#on"),
    };
}

test("the low and high priority stars are visually distinct", async () => {
    const { off, on } = mountStars();
    expect(getComputedStyle(off).color).not.toBe(getComputedStyle(on).color);
});

test("each state selects its own Font Awesome weight", async () => {
    const { off, on } = mountStars();
    expect(getComputedStyle(off).getPropertyValue("--fa-style").trim()).toBe("400");
    expect(getComputedStyle(on).getPropertyValue("--fa-style").trim()).toBe("900");
});

test("neither state relies on the removed \\f006 glyph", async () => {
    const { off, on } = mountStars();
    for (const el of [off, on]) {
        expect(getComputedStyle(el, "::before").content).not.toInclude("f006");
    }
});
