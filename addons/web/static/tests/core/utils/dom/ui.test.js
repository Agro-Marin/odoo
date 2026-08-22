// @ts-check

import { describe, expect, getFixture, test } from "@odoo/hoot";
import { addLoadingEffect } from "@web/core/utils/dom/ui";

describe.current.tags("headless");

/**
 * @param {string} html
 * @returns {HTMLElement}
 */
function mount(html) {
    const fixture = /** @type {HTMLElement} */ (getFixture());
    fixture.innerHTML = html;
    return /** @type {HTMLElement} */ (fixture.firstElementChild);
}

test("the effect marks the button busy and the undo takes it back", async () => {
    const btn = mount(`<button class="btn">go</button>`);
    const restore = addLoadingEffect(/** @type {HTMLButtonElement} */ (btn));
    expect(btn).toHaveClass(["o_btn_loading", "disabled", "pe-none"]);
    expect(/** @type {HTMLButtonElement} */ (btn).disabled).toBe(true);
    expect(btn.querySelector(".fa-spin")).not.toBe(null);

    restore();
    expect(btn).not.toHaveClass("o_btn_loading");
    expect(btn).not.toHaveClass("disabled");
    expect(btn).not.toHaveClass("pe-none");
    expect(/** @type {HTMLButtonElement} */ (btn).disabled).toBe(false);
    expect(btn.querySelector(".fa-spin")).toBe(null);
});

test("the undo does not re-enable a button that was already inert", async () => {
    const btn = /** @type {HTMLButtonElement} */ (
        mount(`<button class="btn disabled pe-none" disabled="disabled">go</button>`)
    );
    addLoadingEffect(btn)();
    expect(btn).toHaveClass(["disabled", "pe-none"]);
    expect(btn.disabled).toBe(true);
});

test("the undo does not re-enable an anchor that was already inert", async () => {
    const link = mount(`<a class="btn disabled pe-none" href="#">go</a>`);
    addLoadingEffect(/** @type {any} */ (link))();
    expect(link).toHaveClass(["disabled", "pe-none"]);
    expect("disabled" in link).toBe(false);
});

test("nesting two effects leaves the button busy until the outer one undoes", async () => {
    const btn = /** @type {HTMLButtonElement} */ (
        mount(`<button class="btn">go</button>`)
    );
    const outerRestore = addLoadingEffect(btn);
    const innerRestore = addLoadingEffect(btn);

    innerRestore();
    expect(btn.disabled).toBe(true);
    expect(btn).toHaveClass("pe-none");

    outerRestore();
    expect(btn.disabled).toBe(false);
    expect(btn).not.toHaveClass("pe-none");
});
