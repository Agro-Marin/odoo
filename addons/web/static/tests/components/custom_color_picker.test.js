// @ts-check

import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { CustomColorPicker } from "@web/components/color_picker/custom_color_picker/custom_color_picker";

test("entering a 6-digit hex preserves the current opacity", async () => {
    // defaultOpacity 50 -> the derived selected color is "#FF000080" (50% alpha,
    // i.e. 128/255 -> ~50.196% once parsed back).
    const picker = await mountWithCleanup(CustomColorPicker, {
        props: {
            defaultOpacity: 50,
        },
    });
    await animationFrame();

    // Opacity is set (< 100%) before typing.
    const opacityBefore = picker.colorComponents.opacity;
    expect(opacityBefore).toBeLessThan(100);

    // Type a 6-digit hex (carries no alpha channel).
    const hexInput = /** @type {HTMLInputElement} */ (
        picker.el.querySelector("input.o_hex_input")
    );
    hexInput.value = "00FF00";
    hexInput.dispatchEvent(new InputEvent("input", { bubbles: true }));
    await animationFrame();

    // The new color is applied...
    expect(picker.colorComponents.red).toBe(0);
    expect(picker.colorComponents.green).toBe(255);
    expect(picker.colorComponents.blue).toBe(0);
    // ...but the opacity must be unchanged. Regression: a 6-digit hex parse
    // fills in opacity: 100, which used to be copied over and silently reset
    // the user-set opacity.
    expect(picker.colorComponents.opacity).toBe(opacityBefore);
});

test("entering an 8-digit hex updates the opacity from its alpha channel", async () => {
    const picker = await mountWithCleanup(CustomColorPicker, {
        props: {
            defaultOpacity: 50,
        },
    });
    await animationFrame();

    expect(picker.colorComponents.opacity).toBeLessThan(100);

    // An 8-digit hex DOES carry an alpha channel (0xFF = 100%): honor it.
    const hexInput = /** @type {HTMLInputElement} */ (
        picker.el.querySelector("input.o_hex_input")
    );
    hexInput.value = "00FF00FF";
    hexInput.dispatchEvent(new InputEvent("input", { bubbles: true }));
    await animationFrame();

    expect(picker.colorComponents.green).toBe(255);
    expect(picker.colorComponents.opacity).toBe(100);
});
