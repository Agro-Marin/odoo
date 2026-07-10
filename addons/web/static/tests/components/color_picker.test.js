// @ts-check

import { expect, test } from "@odoo/hoot";
import {
    animationFrame,
    click,
    manuallyDispatchProgrammaticEvent,
    press,
    queryOne,
} from "@odoo/hoot-dom";
import { Component, useState, xml } from "@odoo/owl";
import { defineStyle, mountWithCleanup } from "@web/../tests/web_test_helpers";
import {
    ColorPicker,
    DEFAULT_COLORS,
    useColorPicker,
} from "@web/components/color_picker/color_picker";
import { CustomColorPicker } from "@web/components/color_picker/custom_color_picker/custom_color_picker";
import { registry } from "@web/core/registry";

test("basic rendering", async () => {
    await mountWithCleanup(ColorPicker, {
        props: {
            state: {
                selectedColor: "",
                defaultTab: "",
            },
            getUsedCustomColors: () => [],
            applyColor() {},
            applyColorPreview() {},
            applyColorResetPreview() {},
            colorPrefix: "",
        },
    });
    expect(".o_font_color_selector").toHaveCount(1);
    expect(".o_font_color_selector .btn-tab").toHaveCount(2);
    expect(".o_font_color_selector .btn.fa-trash").toHaveCount(1);
    expect(".o_font_color_selector .o_colorpicker_section").toHaveCount(1);
    expect(".o_font_color_selector .o_colorpicker_section .o_color_button").toHaveCount(
        5,
    );
    expect(
        ".o_font_color_selector .o_color_section .o_color_button[data-color]",
    ).toHaveCount(DEFAULT_COLORS.flat().length);
});

test("basic rendering with selected color", async () => {
    await mountWithCleanup(ColorPicker, {
        props: {
            state: {
                selectedColor: "#B5D6A5",
                defaultTab: "",
            },
            getUsedCustomColors: () => [],
            applyColor() {},
            applyColorPreview() {},
            applyColorResetPreview() {},
            colorPrefix: "",
        },
    });
    expect(".o_font_color_selector").toHaveCount(1);
    expect(
        ".o_font_color_selector .o_color_section .o_color_button[data-color]",
    ).toHaveCount(DEFAULT_COLORS.flat().length);
    expect(
        ".o_font_color_selector .o_color_section .o_color_button[data-color='#B5D6A5'].selected",
    ).toHaveCount(1);
});

test("keyboard navigation", async () => {
    await mountWithCleanup(ColorPicker, {
        props: {
            state: {
                selectedColor: "",
                defaultTab: "",
            },
            getUsedCustomColors: () => [],
            applyColor() {},
            applyColorPreview() {},
            applyColorResetPreview() {},
            colorPrefix: "",
        },
    });
    await click(
        ".o_font_color_selector .o_color_section .o_color_button[data-color]:first-of-type",
    );
    await animationFrame();
    expect(
        ".o_font_color_selector .o_color_section .o_color_button[data-color]:first-of-type",
    ).toBeFocused();

    await press("arrowright");
    expect(
        ".o_font_color_selector .o_color_section .o_color_button[data-color]:nth-of-type(2)",
    ).toBeFocused();

    await press("enter");
    await animationFrame();
    expect(
        ".o_font_color_selector .o_color_section .o_color_button[data-color]:nth-of-type(2)",
    ).toHaveClass("selected");

    await press("arrowleft");
    expect(
        ".o_font_color_selector .o_color_section .o_color_button[data-color]:first-of-type",
    ).toBeFocused();

    // cannot move if no previous color
    await press("arrowleft");
    expect(
        ".o_font_color_selector .o_color_section .o_color_button[data-color]:first-of-type",
    ).toBeFocused();

    await press("arrowdown");
    expect(
        ".o_font_color_selector .o_color_section .o_color_button[data-color]:nth-of-type(9)",
    ).toBeFocused();

    await press("arrowup");
    expect(
        ".o_font_color_selector .o_color_section .o_color_button[data-color]:first-of-type",
    ).toBeFocused();

    await click(
        ".o_font_color_selector .o_color_section .o_color_button[data-color]:nth-of-type(8)",
    );
    await animationFrame();

    await press("arrowright");
    expect(
        ".o_font_color_selector .o_color_section .o_color_button[data-color]:nth-of-type(9)",
    ).toBeFocused();

    await press("arrowleft");
    expect(
        ".o_font_color_selector .o_color_section .o_color_button[data-color]:nth-of-type(8)",
    ).toBeFocused();

    await click(
        ".o_font_color_selector .o_color_section .o_color_button[data-color]:last-of-type",
    );
    await animationFrame();
    expect(
        ".o_font_color_selector .o_color_section .o_color_button[data-color]:last-of-type",
    ).toBeFocused();

    // cannot move if no next color
    await press("arrowright");
    expect(
        ".o_font_color_selector .o_color_section .o_color_button[data-color]:last-of-type",
    ).toBeFocused();
});

test("colorpicker inside the builder are linked to the builder theme colors", async () => {
    await mountWithCleanup(ColorPicker, {
        props: {
            state: {
                selectedColor: "",
                defaultTab: "",
            },
            getUsedCustomColors: () => [],
            applyColor() {},
            applyColorPreview() {},
            applyColorResetPreview() {},
            colorPrefix: "",
            cssVarColorPrefix: "xyz-",
        },
    });
    const getButtonColor = (sel) => getComputedStyle(queryOne(sel)).backgroundColor;

    defineStyle(`
        :root {
            --o-color-1: rgb(113, 75, 103);
            --o-color-2: rgb(45, 49, 66);
            --xyz-o-color-1: rgb(113, 75, 103);
            --xyz-o-color-2: rgb(45, 49, 66);
        }
    `);
    expect(getButtonColor("button[data-color='o-color-1']")).toBe("rgb(113, 75, 103)");
    expect(getButtonColor("button[data-color='o-color-2']")).toBe("rgb(45, 49, 66)");

    defineStyle(`
        :root {
            --xyz-o-color-1: rgb(0, 0, 255);
            --xyz-o-color-2: rgb(0, 255, 0);
        }
    `);
    expect(getButtonColor("button[data-color='o-color-1']")).toBe("rgb(0, 0, 255)");
    expect(getButtonColor("button[data-color='o-color-2']")).toBe("rgb(0, 255, 0)");
});

test("colorpicker outside the builder are not linked to the builder theme colors", async () => {
    await mountWithCleanup(ColorPicker, {
        props: {
            state: {
                selectedColor: "",
                defaultTab: "",
            },
            getUsedCustomColors: () => [],
            applyColor() {},
            applyColorPreview() {},
            applyColorResetPreview() {},
            colorPrefix: "",
            cssVarColorPrefix: "",
        },
    });
    const getButtonColor = (sel) => getComputedStyle(queryOne(sel)).backgroundColor;

    defineStyle(`
        :root {
            --o-color-1: rgb(113, 75, 103);
            --o-color-2: rgb(45, 49, 66);
            --xyz-o-color-1: rgb(113, 75, 103);
            --xyz-o-color-2: rgb(45, 49, 66);
        }
    `);
    expect(getButtonColor("button[data-color='o-color-1']")).toBe("rgb(113, 75, 103)");
    expect(getButtonColor("button[data-color='o-color-2']")).toBe("rgb(45, 49, 66)");

    defineStyle(`
        :root {
            --xyz-o-color-1: rgb(0, 0, 255);
            --xyz-o-color-2: rgb(0, 255, 0);
        }
    `);
    expect(getButtonColor("button[data-color='o-color-1']")).toBe("rgb(113, 75, 103)");
    expect(getButtonColor("button[data-color='o-color-2']")).toBe("rgb(45, 49, 66)");
});

test("custom color picker sets default color as selected", async () => {
    await mountWithCleanup(CustomColorPicker, {
        props: {
            defaultColor: "#FF0000",
        },
    });
    expect("input.o_hex_input").toHaveValue("#FF0000");
});

test("AGROMARINVERIFY custom color picker does not mutate its props", async () => {
    const picker = await mountWithCleanup(CustomColorPicker, {
        props: { defaultColor: "#FF0000", defaultOpacity: 0.5 },
    });
    // OWL props are owned by the parent: the component must not rewrite them
    // (the old in-place mutation was also non-idempotent).
    expect(picker.props.defaultColor).toBe("#FF0000");
    expect(picker.props.defaultOpacity).toBe(0.5);
    // Derived display values live on the instance instead.
    expect(picker.defaultOpacity).toBe(50); // 0.5 in (0,1] scaled to a percentage
    expect(picker.defaultColor).toBe("#FF000080"); // opacity hex appended once
    expect(picker.selectedColor).toBe("#FF000080"); // falls back to defaultColor
});

test("should preserve color slider when picking max lightness color", async () => {
    class TestColorPicker extends Component {
        static template = xml`
            <div style="width: 222px">
                <CustomColorPicker selectedColor="state.color" onColorPreview.bind="onColorChange" onColorSelect.bind="onColorChange"/>
            </div>`;
        static components = { CustomColorPicker };
        static props = ["*"];
        setup() {
            this.state = useState({
                color: "#FFFF00",
            });
        }
        onColorChange({ cssColor }) {
            this.state.color = cssColor;
        }
    }
    await mountWithCleanup(TestColorPicker);
    const colorPickerArea = queryOne(".o_color_pick_area");
    const colorPickerRect = colorPickerArea.getBoundingClientRect();

    const clientX = colorPickerRect.left + colorPickerRect.width / 2;
    const clientY = colorPickerRect.top; // Lightness 100%
    manuallyDispatchProgrammaticEvent(colorPickerArea, "pointerdown", {
        clientX,
        clientY,
    });
    manuallyDispatchProgrammaticEvent(colorPickerArea, "pointerup", {
        clientX,
        clientY,
    });

    await animationFrame();
    expect(colorPickerArea).toHaveStyle({ backgroundColor: "rgb(255, 255, 0)" });
});

test("custom color picker change color on click in hue slider", async () => {
    await mountWithCleanup(CustomColorPicker, { props: { selectedColor: "#FF0000" } });
    expect("input.o_hex_input").toHaveValue("#FF0000");
    await click(".o_color_slider");
    expect("input.o_hex_input").not.toHaveValue("#FF0000");
});

class ExtraTab extends Component {
    static template = xml`<p>Color picker extra tab</p>`;
    static props = ["*"];
}

test("can register an extra tab", async () => {
    registry.category("color_picker_tabs").add("web.extra", {
        id: "extra",
        name: "Extra",
        component: ExtraTab,
    });
    await mountWithCleanup(ColorPicker, {
        props: {
            state: {
                selectedColor: "#FF0000",
                defaultTab: "",
            },
            getUsedCustomColors: () => [],
            applyColor() {},
            applyColorPreview() {},
            applyColorResetPreview() {},
            colorPrefix: "",
            enabledTabs: ["solid", "custom", "extra"],
        },
    });
    expect(".o_font_color_selector .btn-tab").toHaveCount(3);
    await click("button.extra-tab");
    await animationFrame();
    expect("button.extra-tab").toHaveClass("active");
    expect(".o_font_color_selector>p:last-child").toHaveText("Color picker extra tab");
    registry.category("color_picker_tabs").remove("web.extra");
});

test("useColorPicker commits the previewed custom color on close without a caller onClose", async () => {
    /** @type {Record<string, any>} */
    const pickerOptions = {};
    class Host extends Component {
        static template = xml`<button class="test-color-btn" t-ref="colorButton">color</button>`;
        static props = ["*"];
        setup() {
            this.colorState = useState({
                selectedColor: "#FF0000",
                defaultTab: "custom",
            });
            // No `onClose` in the options: the previewed custom color must
            // still be committed when the popover closes.
            this.picker = useColorPicker(
                "colorButton",
                {
                    state: this.colorState,
                    getUsedCustomColors: () => [],
                    applyColor: () => expect.step("applyColor"),
                    applyColorPreview: () => {},
                    applyColorResetPreview: () => {},
                    colorPrefix: "",
                },
                pickerOptions,
            );
        }
    }
    const comp = await mountWithCleanup(Host);
    await click(".test-color-btn");
    await animationFrame();
    expect(".o_font_color_selector").toHaveCount(1);
    expect(".o_color_pick_area").toHaveCount(1);

    // Preview a color by dragging on the picking area.
    const colorPickerArea = queryOne(".o_color_pick_area");
    const colorPickerRect = colorPickerArea.getBoundingClientRect();
    const clientX = colorPickerRect.left + colorPickerRect.width / 2;
    const clientY = colorPickerRect.top + colorPickerRect.height / 2;
    manuallyDispatchProgrammaticEvent(colorPickerArea, "pointerdown", {
        clientX,
        clientY,
    });
    manuallyDispatchProgrammaticEvent(colorPickerArea, "pointerup", {
        clientX,
        clientY,
    });
    await animationFrame();
    // The dragged color is only previewed at this point, not committed.
    expect.verifySteps([]);

    /** @type {any} */ (comp).picker.close();
    await animationFrame();
    // Closing the popover commits the previewed color.
    expect.verifySteps(["applyColor"]);
    // The hook must not mutate the caller's options object.
    expect("onClose" in pickerOptions).toBe(false);
});

test("should mark default color as selected when it is selected", async () => {
    defineStyle(`
        :root {
            --900: #212527;
        }
    `);
    await mountWithCleanup(ColorPicker, {
        props: {
            state: {
                selectedColor: "#212527",
                defaultTab: "custom",
            },
            getUsedCustomColors: () => [],
            applyColor() {},
            applyColorPreview() {},
            applyColorResetPreview() {},
            colorPrefix: "",
        },
    });
    expect(".o_color_button[data-color='900']").toHaveClass("selected");
});
