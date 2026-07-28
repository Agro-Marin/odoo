// @ts-check

import { expect, test } from "@odoo/hoot";
import {
    animationFrame,
    click,
    manuallyDispatchProgrammaticEvent,
    queryOne,
} from "@odoo/hoot-dom";
import { Component, useState, xml } from "@odoo/owl";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { useColorPicker } from "@web/components/color_picker/color_picker";

test("a second picker session does not replay the previous session's close callback", async () => {
    class Host extends Component {
        static template = xml`<button class="test-color-btn" t-ref="colorButton">color</button>`;
        static props = ["*"];
        setup() {
            this.colorState = useState({
                selectedColor: "#FF0000",
                defaultTab: "custom",
            });
            this.picker = useColorPicker("colorButton", {
                state: this.colorState,
                getUsedCustomColors: () => [],
                applyColor: () => expect.step("applyColor"),
                applyColorPreview: () => {},
                applyColorResetPreview: () => {},
                colorPrefix: "",
            });
        }
    }
    const comp = /** @type {any} */ (await mountWithCleanup(Host));

    // --- session 1: land on the custom tab and pick a colour by dragging.
    await click(".test-color-btn");
    await animationFrame();
    expect(".o_color_pick_area").toHaveCount(1);
    const area = queryOne(".o_color_pick_area");
    const rect = area.getBoundingClientRect();
    const clientX = rect.left + rect.width / 2;
    const clientY = rect.top + rect.height / 2;
    manuallyDispatchProgrammaticEvent(area, "pointerdown", { clientX, clientY });
    manuallyDispatchProgrammaticEvent(area, "pointerup", { clientX, clientY });
    await animationFrame();
    comp.picker.close();
    await animationFrame();
    expect.verifySteps(["applyColor"]);

    // --- session 2: open on the solid tab (no CustomColorPicker is mounted),
    // touch nothing, close. Nothing was picked, so nothing must be applied.
    comp.colorState.defaultTab = "solid";
    await click(".test-color-btn");
    await animationFrame();
    expect(".o_color_pick_area").toHaveCount(0);
    comp.picker.close();
    await animationFrame();
    expect.verifySteps([]);
});
