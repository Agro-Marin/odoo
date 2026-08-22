// @ts-check

import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { CustomColorPicker } from "@web/components/color_picker/custom_color_picker/custom_color_picker";

test("entering a 6-digit hex preserves the current opacity", async () => {
    const picker = await mountWithCleanup(CustomColorPicker, {
        props: {
            defaultOpacity: 50,
        },
    });
    await animationFrame();

    const opacityBefore = picker.colorComponents.opacity;
    expect(opacityBefore).toBeLessThan(100);

    const hexInput = /** @type {HTMLInputElement} */ (
        picker.el.querySelector("input.o_hex_input")
    );
    hexInput.value = "00FF00";
    hexInput.dispatchEvent(new InputEvent("input", { bubbles: true }));
    await animationFrame();

    expect(picker.colorComponents.red).toBe(0);
    expect(picker.colorComponents.green).toBe(255);
    expect(picker.colorComponents.blue).toBe(0);
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

    const hexInput = /** @type {HTMLInputElement} */ (
        picker.el.querySelector("input.o_hex_input")
    );
    hexInput.value = "00FF00FF";
    hexInput.dispatchEvent(new InputEvent("input", { bubbles: true }));
    await animationFrame();

    expect(picker.colorComponents.green).toBe(255);
    expect(picker.colorComponents.opacity).toBe(100);
});

test("a colour the parser cannot read still opens on something", async () => {
    const unparseable = [
        ["", ""],
        ["red", "red"],
        ["var(--o-color-1)", ""],
    ];
    for (const [index, [selectedColor, defaultColor]] of unparseable.entries()) {
        await mountWithCleanup(CustomColorPicker, {
            props: { selectedColor, defaultColor, onColorSelect: () => {} },
        });
        expect(".o_color_pick_area").toHaveCount(index + 1);
    }
});

test("arrows move the picker's two axes, control+ moves them finely", async () => {
    const picker = await mountWithCleanup(CustomColorPicker, {
        props: { selectedColor: "#BF4040", onColorSelect: () => {} },
    });
    await animationFrame();

    const press = (/** @type {string} */ key, /** @type {boolean} */ ctrl = false) =>
        picker.onPickerKeydown(
            /** @type {any} */ ({ key, ctrlKey: ctrl, preventDefault: () => {} }),
        );

    const before = { ...picker.colorComponents };
    press("ArrowUp");
    expect(picker.colorComponents.lightness).toBe(before.lightness + 10);
    expect(picker.colorComponents.saturation).toBe(before.saturation);

    press("ArrowLeft", true);
    expect(picker.colorComponents.saturation).toBe(before.saturation - 1);
    expect(picker.colorComponents.lightness).toBe(before.lightness + 10);

    press("ArrowRight");
    expect(picker.colorComponents.saturation).toBe(before.saturation - 1 + 10);

    for (let i = 0; i < 20; i++) {
        press("ArrowDown");
    }
    expect(picker.colorComponents.lightness).toBe(0);
});
