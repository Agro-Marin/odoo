// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryOne, queryRect } from "@odoo/hoot-dom";
import { Component, useRef, xml } from "@odoo/owl";
import { contains, mountWithCleanup } from "@web/../tests/web_test_helpers";
import { useAutoresize } from "@web/core/utils/dom/autoresize";

/**
 * The width an autoresized input settles on must come from the input's own
 * font. The measuring span is appended to the input's parent, so it inherited
 * *its* typography -- and an `<input>` does not inherit the page font to begin
 * with, so the two routinely differ.
 */
class Sized extends Component {
    static template = xml`
        <div class="host" t-att-style="props.hostStyle">
            <input class="resizable" t-ref="input" t-att-style="props.inputStyle"/>
        </div>`;
    static props = ["*"];
    setup() {
        useAutoresize(useRef("input"));
    }
}

/**
 * Width of ``el``'s value rendered with ``el``'s own font.
 *
 * @param {HTMLInputElement} el
 * @returns {number}
 */
function referenceTextWidth(el) {
    const span = document.createElement("span");
    const style = window.getComputedStyle(el);
    span.style.position = "absolute";
    span.style.visibility = "hidden";
    span.style.whiteSpace = "pre";
    // Set longhands rather than the `font` shorthand: the shorthand cannot
    // represent a non-normal `font-variant-numeric`, and a computed value that
    // cannot be represented comes back as the empty string -- which would
    // leave this reference span with no font at all.
    for (const property of [
        "font-family",
        "font-size",
        "font-style",
        "font-weight",
        "font-stretch",
        "font-variant",
        "font-variant-numeric",
        "letter-spacing",
        "word-spacing",
    ]) {
        span.style.setProperty(property, style.getPropertyValue(property));
    }
    span.textContent = el.value;
    document.body.appendChild(span);
    const width = span.offsetWidth;
    span.remove();
    return width;
}

/**
 * @param {string} hostStyle
 * @param {string} inputStyle
 * @param {string} [text]
 */
async function assertMeasuredWithInputFont(hostStyle, inputStyle, text = "WWWWWWWWWW") {
    await mountWithCleanup(Sized, { props: { hostStyle, inputStyle } });
    await contains(`.resizable`).edit(text);
    const input = /** @type {HTMLInputElement} */ (queryOne(`.resizable`));
    const expected = referenceTextWidth(input);
    expect(Math.abs(queryRect(`.resizable`).width - expected)).toBeLessThan(2);
}

test("a container with a much smaller font does not shrink the box", async () => {
    await assertMeasuredWithInputFont(
        "font-family: monospace; font-size: 8px; width: 600px;",
        "font-family: monospace; font-size: 32px;",
    );
});

test("a container with a much larger font does not stretch the box", async () => {
    await assertMeasuredWithInputFont(
        "font-family: monospace; font-size: 40px; width: 600px;",
        "font-family: monospace; font-size: 11px;",
    );
});

test("letter-spacing on the input is accounted for", async () => {
    await assertMeasuredWithInputFont(
        "font-family: monospace; font-size: 14px; width: 600px;",
        "font-family: monospace; font-size: 14px; letter-spacing: 4px;",
    );
});

test("a numeric variant the container lacks is accounted for", async () => {
    // `font-variant-numeric` is not part of the `font` shorthand, and tabular
    // figures do not have the same advance as proportional ones.
    await assertMeasuredWithInputFont(
        "font-family: monospace; font-size: 14px; width: 600px;",
        "font-family: serif; font-size: 14px; font-variant-numeric: tabular-nums;",
        "10.01 21.72 38.94",
    );
});
