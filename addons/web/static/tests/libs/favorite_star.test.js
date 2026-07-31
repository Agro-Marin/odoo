// @ts-check

import { describe, expect, getFixture, test } from "@odoo/hoot";

describe.current.tags("headless");

/**
 * The favourite widgets encode their state in the Font Awesome family class
 * (`fa-regular` empty / `fa-solid` filled) since FA7 dropped the separate
 * outline glyph. Styling keyed on the old `fa-star-o` name silently stops
 * matching, so both states render identically - which no behavioural test can catch.
 */
function mountStars(/** @type {string} */ wrapperClass, iconTag = "i") {
    const fixture = getFixture();
    fixture.innerHTML = `
        <div class="${wrapperClass}" id="off"><${iconTag} class="fa-regular fa-star me-1"></${iconTag}></div>
        <div class="${wrapperClass}" id="on"><${iconTag} class="fa-solid fa-star me-1"></${iconTag}></div>`;
    return {
        off: getComputedStyle(fixture.querySelector("#off " + iconTag)),
        on: getComputedStyle(fixture.querySelector("#on " + iconTag)),
    };
}

test("boolean_favorite: the two states are visually distinct", async () => {
    const { off, on } = mountStars("o_field_widget o_favorite");
    expect(off.color).not.toBe(on.color);
});

test("boolean_favorite: the filled star uses the favourite colour", async () => {
    const { on } = mountStars("o_field_widget o_favorite");
    expect(on.color).toBe("rgb(243, 204, 0)");
});

test("boolean_favorite: font-size custom property still applies", async () => {
    const fixture = getFixture();
    fixture.innerHTML = `<div class="o_field_widget o_favorite" style="--Favorite-font-size: 3rem">
        <i class="fa-regular fa-star me-1"></i></div>`;
    expect(getComputedStyle(fixture.querySelector("i")).fontSize).toBe("48px");
});

test("the FA4 outline-star codepoint is gone, so nothing may rely on it", async () => {
    const fixture = getFixture();
    fixture.innerHTML = `<i class="fa-solid fa-star" id="s"></i>`;
    const content = getComputedStyle(fixture.querySelector("#s"), "::before").content;
    expect(content).not.toInclude("f006");
});
