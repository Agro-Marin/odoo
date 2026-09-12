import { expect, test } from "@odoo/hoot";
import { animationFrame, click } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { ColorPicker } from "@web/components/color_picker";

test("inserting a gradient stop blends color and alpha at percentage precision", async () => {
    const picker = await mountWithCleanup(GradientPicker, {
        props: {
            selectedGradient:
                "linear-gradient(90deg, rgba(0, 0, 0, 0) 0%, rgb(255, 255, 255) 100%)",
        },
    });
    picker.addColorStop(25);
    expect(picker.colors[1]).toEqual({
        hex: "rgba(64, 64, 64, 0.25)",
        percentage: 25,
    });
});

test("gradient pickers can omit callbacks and edit independent default stops", async () => {
    const first = await mountWithCleanup(GradientPicker, { props: {} });
    const second = await mountWithCleanup(GradientPicker, { props: {} });
    first.addColorStop(50);
    expect(first.colors).toHaveLength(3);
    expect(second.colors).toEqual([
        { hex: "#DF7CC4", percentage: 0 },
        { hex: "#6C3582", percentage: 100 },
    ]);
});

test("custom gradient must be defined", async () => {
    await mountWithCleanup(ColorPicker, {
        props: {
            state: {
                selectedColor: "",
                defaultTab: "gradient",
            },
            getUsedCustomColors: () => [],
            applyColor() {},
            applyColorPreview() {},
            applyColorResetPreview() {},
            colorPrefix: "",
            enabledTabs: ["gradient"],
        },
    });
    await click(".o_custom_gradient_button");
    await animationFrame();
    expect(".gradient-colors input[type='range']").toHaveCount(2);
});
import { GradientPicker } from "@html_editor/main/font/gradient_picker/gradient_picker";
