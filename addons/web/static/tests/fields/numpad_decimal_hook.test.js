// @ts-check

import { expect, test } from "@odoo/hoot";
import { press, queryFirst } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import { defineParams, mountWithCleanup } from "@web/../tests/web_test_helpers";
import { useNumpadDecimal } from "@web/fields/numpad_decimal_hook";

/**
 * `localization` is a lazy parameter bag: reading `decimalPoint` before the
 * parameters land throws, so the separator has to be declared rather than
 * patched onto the object.
 *
 * @param {string} decimalPoint
 */
function useSeparator(decimalPoint) {
    defineParams(
        { lang_parameters: { decimal_point: decimalPoint } },
        { mode: "replace" },
    );
}

/**
 * The hook is attached to a *container*, not to the input, because two of its
 * six consumers (progressbar, monetary) have more than one input under one ref.
 * Every test therefore mounts the shape the widgets actually use.
 *
 * @param {string} [inner]
 */
async function mountHost(inner = `<input type="text" class="target"/>`) {
    class Host extends Component {
        static template = xml`<div t-ref="numpadDecimal">${inner}</div>`;
        /** @type {any} */
        static props = [];
        setup() {
            useNumpadDecimal();
        }
    }
    await mountWithCleanup(Host);
    await animationFrame();
}

/**
 * `press` alone cannot say *which* physical key produced a character, and the
 * whole hook keys off that: only the numpad's own decimal key is rewritten.
 *
 * @param {HTMLElement} el
 * @param {string} key
 * @param {string} code
 * @returns {boolean} whether the default was prevented
 */
function keydown(el, key, code) {
    const ev = new KeyboardEvent("keydown", {
        key,
        code,
        bubbles: true,
        cancelable: true,
    });
    el.dispatchEvent(ev);
    return ev.defaultPrevented;
}

test("the numpad decimal key types the locale's separator, not the key's own", async () => {
    useSeparator(",");
    await mountHost();
    const input = /** @type {HTMLInputElement} */ (queryFirst("input.target"));
    input.focus();
    input.value = "12";
    input.setSelectionRange(2, 2);

    expect(keydown(input, ".", "NumpadDecimal")).toBe(true);
    expect(input.value).toBe("12,");
});

test("it replaces the selection rather than appending", async () => {
    useSeparator(",");
    await mountHost();
    const input = /** @type {HTMLInputElement} */ (queryFirst("input.target"));
    input.focus();
    input.value = "12x45";
    input.setSelectionRange(2, 3);

    keydown(input, ".", "NumpadDecimal");
    expect(input.value).toBe("12,45");
});

test("it fires a bubbling input event, so useInputField sees the edit", async () => {
    useSeparator(",");
    await mountHost();
    const input = /** @type {HTMLInputElement} */ (queryFirst("input.target"));
    /** @type {string[]} */
    const seen = [];
    input.closest("div")?.addEventListener("input", () => seen.push("input"));
    input.focus();
    input.value = "1";
    input.setSelectionRange(1, 1);

    keydown(input, ".", "NumpadDecimal");
    expect(seen).toEqual(["input"]);
});

test("it leaves the key alone when it already is the locale's separator", async () => {
    useSeparator(".");
    await mountHost();
    const input = /** @type {HTMLInputElement} */ (queryFirst("input.target"));
    input.focus();
    input.value = "12";
    input.setSelectionRange(2, 2);

    // Not prevented, so the browser types the "." itself -- rewriting it here
    // would insert one character and let the browser insert a second.
    expect(keydown(input, ".", "NumpadDecimal")).toBe(false);
    expect(input.value).toBe("12");
});

test("the main-row period is left alone -- only the numpad key is rewritten", async () => {
    useSeparator(",");
    await mountHost();
    const input = /** @type {HTMLInputElement} */ (queryFirst("input.target"));
    input.focus();
    input.value = "12";
    input.setSelectionRange(2, 2);

    expect(keydown(input, ".", "Period")).toBe(false);
    expect(input.value).toBe("12");
});

test("a native number input is left alone -- it only accepts its own separator", async () => {
    useSeparator(",");
    await mountHost(`<input type="number" class="target"/>`);
    const input = /** @type {HTMLInputElement} */ (queryFirst("input.target"));
    input.focus();

    expect(keydown(input, ".", "NumpadDecimal")).toBe(false);
});

test("a keydown outside any input is ignored", async () => {
    useSeparator(",");
    await mountHost(
        `<span class="outside">x</span><input type="text" class="target"/>`,
    );
    const outside = /** @type {HTMLElement} */ (queryFirst("span.outside"));

    expect(keydown(outside, ".", "NumpadDecimal")).toBe(false);
});

test("focusing an input selects it, so the next keystroke replaces the value", async () => {
    await mountHost();
    const input = /** @type {HTMLInputElement} */ (queryFirst("input.target"));
    input.value = "1234";
    input.focus();
    await animationFrame();

    expect([input.selectionStart, input.selectionEnd]).toEqual([0, 4]);
});

test("the hook works when the ref is the input itself, not a container", async () => {
    useSeparator(",");

    class Host extends Component {
        static template = xml`<input type="text" class="target" t-ref="numpadDecimal"/>`;
        /** @type {any} */
        static props = [];
        setup() {
            useNumpadDecimal();
        }
    }
    await mountWithCleanup(Host);
    await animationFrame();

    const input = /** @type {HTMLInputElement} */ (queryFirst("input.target"));
    input.focus();
    input.value = "7";
    input.setSelectionRange(1, 1);

    keydown(input, ".", "NumpadDecimal");
    expect(input.value).toBe("7,");
});

// End to end through hoot's own press() rather than a hand-built event, to show
// the hook is really attached and really declines: press(".") emits the main-row
// `Period`, so the "." must arrive verbatim even under a comma locale.
test("a typed period is not rewritten -- only the numpad key is", async () => {
    useSeparator(",");
    await mountHost();
    const input = /** @type {HTMLInputElement} */ (queryFirst("input.target"));
    input.focus();
    input.value = "3";
    input.setSelectionRange(1, 1);

    await press(".");
    expect(input.value).toBe("3.");
});
