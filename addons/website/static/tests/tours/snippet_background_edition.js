import { backgroundImageCssToParts } from "@html_editor/utils/image";
import {
    changeBackgroundColor,
    changeOption,
    clickOnEditAndWaitEditMode,
    clickOnSave,
    clickOnSnippet,
    insertSnippet,
    registerWebsitePreviewTour,
} from "@website/js/tours/tour_utils";

const snippets = [
    {
        id: "s_text_image",
        name: "Text - Image",
        groupName: "Content",
    },
];
const backgroundColors = [
    {
        code: "200",
        hex: "#e9ecef",
    },
    {
        code: "800",
        hex: "#343a40",
    },
];
const gradients = [
    "linear-gradient(135deg, rgb(203, 94, 238) 0%, rgb(75, 225, 236) 100%)",
    "linear-gradient(135deg, rgb(255, 222, 202) 0%, rgb(202, 115, 69) 100%)",
];

function typeToName(xType) {
    return xType === "cc" ? "Theme" : xType === "bg" ? "Custom" : "Gradient";
}

function switchTo(type, _name) {
    const name = _name || typeToName(type);
    return {
        trigger: `.o_font_color_selector .btn-tab:contains("${name}")`,
        content: `Switch to ${name}`,
        run: "click",
    };
}

function addCheck(steps, checkX, checkNoX, xType, noSwitch = false) {
    if (!checkX && !checkNoX) {
        return;
    }

    const name = typeToName(xType);
    const selectorCheckX = checkX && `[data-color="${checkX}"].selected`;
    const selectorCheckNoX = checkNoX
        ? `[data-color="${checkNoX}"]:not(.selected)`
        : null;

    const step = {
        trigger: selectorCheckX || selectorCheckNoX,
        content: `The correct ${name} is marked as selected`,
        tooltipPosition: "bottom",
    };
    if (!noSwitch) {
        steps.push(switchTo(xType, name));
    }
    if (!selectorCheckX && selectorCheckNoX) {
        steps.push({
            trigger: selectorCheckNoX,
        });
    }
    steps.push(step);
}

function checkAndUpdateBackgroundColor({
    checkCC,
    checkNoCC,
    checkBg,
    checkNoBg,
    checkGradient,
    checkNoGradient,
    changeType,
    change,
    finalSelector,
    finalRun,
}) {
    const steps = [changeBackgroundColor()];

    addCheck(steps, checkCC, checkNoCC, "cc");
    addCheck(steps, checkBg, checkNoBg, "bg");
    addCheck(steps, checkGradient, checkNoGradient, "gradient");

    if (changeType) {
        steps.push(switchTo(changeType));
        steps.push({
            content: "Change background color",
            trigger: `.o_popover [data-color="${change}"]`,
            run: "click",
        });
        steps.push({
            trigger: finalSelector,
            content: "The selected colors have been applied (CC AND (BG or GRADIENT))",
            tooltipPosition: "bottom",
            run: finalRun,
        });
    }

    return steps;
}

function updateAndCheckCustomGradient({ updateStep, checkGradient }) {
    const steps = [updateStep];
    addCheck(
        steps,
        checkGradient,
        checkGradient !== gradients[0] && gradients[0],
        "gradient",
        true,
    );
    return steps;
}

registerWebsitePreviewTour(
    "snippet_background_edition",
    {
        url: "/",
        edition: true,
    },
    () => [
        ...insertSnippet(snippets[0]),
        ...clickOnSnippet(snippets[0]),

        changeOption("Text - Image", "button[data-action-id='toggleBgImage']"),
        {
            content: "Click on image",
            trigger: ".o_select_media_dialog .o_button_area[aria-label='test.png']",
            run: "click",
        },
        ...clickOnSave(),
        {
            content: "Check that the image is set",
            trigger: `:iframe section.${snippets[0].id}[style^="background-image: url("]`,
        },
        ...clickOnEditAndWaitEditMode(),
        ...clickOnSnippet(snippets[0]),
        changeOption("Text - Image", "button[data-action-id='toggleBgImage']"),

        ...checkAndUpdateBackgroundColor({
            changeType: "cc",
            change: "o_cc3",
            finalSelector: `:iframe .${snippets[0].id}.o_cc3:not([class*=bg-]):not([style*="background"])`,
        }),

        ...checkAndUpdateBackgroundColor({
            checkCC: "o_cc3",
            changeType: "cc",
            change: "o_cc2",
            finalSelector: `:iframe .${snippets[0].id}.o_cc2:not(.o_cc3):not([class*=bg-])`,
        }),

        ...checkAndUpdateBackgroundColor({
            checkCC: "o_cc2",
            checkNoCC: "o_cc3",
            changeType: "bg",
            change: backgroundColors[0].code,
            finalSelector: `:iframe .${snippets[0].id}.o_cc2.bg-${backgroundColors[0].code}`,
        }),

        ...checkAndUpdateBackgroundColor({
            checkCC: "o_cc2",
            checkBg: backgroundColors[0].code,
            changeType: "bg",
            change: backgroundColors[1].code,
            finalSelector: `:iframe .${snippets[0].id}.o_cc2.bg-${backgroundColors[1].code}:not(.bg-${backgroundColors[0].code})`,
        }),

        ...checkAndUpdateBackgroundColor({
            checkCC: "o_cc2",
            checkNoBg: backgroundColors[0].code,
            changeType: "cc",
            change: "o_cc4",
            finalSelector: `:iframe .${snippets[0].id}.o_cc4:not(.o_cc2):not(.bg-${backgroundColors[1].code})`,
        }),

        ...checkAndUpdateBackgroundColor({
            checkCC: "o_cc4",
            checkNoCC: "o_cc2",
            checkNoBg: backgroundColors[1].code,
            changeType: "gradient",
            change: gradients[0],
            finalSelector: `:iframe .${snippets[0].id}.o_cc4:not(.bg-${backgroundColors[1].code})[style*="background-image: ${gradients[0]}"]`,
        }),

        ...checkAndUpdateBackgroundColor({
            checkCC: "o_cc4",
            checkNoBg: backgroundColors[1].code,
            checkGradient: gradients[0],
            changeType: "gradient",
            change: gradients[1],
            finalSelector: `:iframe .${snippets[0].id}.o_cc4[style*="background-image: ${gradients[1]}"]:not([style*="background-image: ${gradients[0]}"])`,
        }),

        ...checkAndUpdateBackgroundColor({
            checkCC: "o_cc4",
            checkGradient: gradients[1],
            checkNoGradient: gradients[0],
            changeType: "cc",
            change: "o_cc1",
            finalSelector: `:iframe .${snippets[0].id}.o_cc1:not(.o_cc4):not([style*="background-image: ${gradients[1]}"])`,
        }),

        ...checkAndUpdateBackgroundColor({
            checkCC: "o_cc1",
            checkNoCC: "o_cc4",
            checkNoGradient: gradients[1],
            changeType: "gradient",
            change: gradients[1],
            finalSelector: `:iframe .${snippets[0].id}.o_cc1:not(.o_cc4)[style*="background-image: ${gradients[1]}"]`,
        }),

        changeOption("Text - Image", "button[data-action-id='toggleBgImage']"),
        {
            trigger: ".o_existing_attachment_cell .o_button_area",
            content: "Select an image in the media dialog",
            run: "click",
        },
        {
            trigger: `:iframe .${snippets[0].id}.o_cc1`,
            run: function () {
                const parts = backgroundImageCssToParts(
                    getComputedStyle(this.anchor)["background-image"],
                );
                if (!parts.url || !parts.url.startsWith("url(")) {
                    throw new Error("An image should have been added as background.");
                }
                if (parts.gradient !== gradients[1]) {
                    throw new Error(
                        "The gradient should have been kept when adding the background image",
                    );
                }
            },
        },

        ...checkAndUpdateBackgroundColor({
            checkCC: "o_cc1",
            checkGradient: gradients[1],
            changeType: "gradient",
            change: gradients[0],
            finalSelector: `:iframe .${snippets[0].id}.o_cc1:not([style*="${gradients[1]}"])`,
            finalRun: function () {
                const parts = backgroundImageCssToParts(
                    getComputedStyle(this.anchor)["background-image"],
                );
                if (!parts.url || !parts.url.startsWith("url(")) {
                    throw new Error(
                        "The image should have been kept when changing the gradient",
                    );
                }
                if (parts.gradient !== gradients[0]) {
                    throw new Error("The gradient should have been changed");
                }
            },
        }),

        changeBackgroundColor(),
        switchTo("gradient"),
        {
            content: "Click on 'Custom' button to show custom gradient options",
            trigger: ".o_popover .o_custom_gradient_button",
            run: "click",
        },
        ...updateAndCheckCustomGradient({
            updateStep: {
                trigger: ".o_popover .gradient-preview",
                content: "Add step",
                run: "click",
            },
            checkGradient:
                "linear-gradient(135deg, rgb(203, 94, 238) 0%, rgb(139, 160, 237) 50%, rgb(75, 225, 236) 100%)",
        }),
        ...updateAndCheckCustomGradient({
            updateStep: {
                trigger: ".o_popover .gradient-colors input.active",
                content: "Move step",
                run: "range 45",
            },
            checkGradient:
                "linear-gradient(135deg, rgb(203, 94, 238) 0%, rgb(139, 160, 237) 45%, rgb(75, 225, 236) 100%)",
        }),
        ...updateAndCheckCustomGradient({
            updateStep: {
                trigger: ".o_popover .o_color_picker_inputs .o_hex_div input",
                content: "Pick step color",
                run: "edit #FF0000",
            },
            checkGradient:
                "linear-gradient(135deg, rgb(203, 94, 238) 0%, rgb(255, 0, 0) 45%, rgb(75, 225, 236) 100%)",
        }),
        ...updateAndCheckCustomGradient({
            updateStep: {
                trigger: ".o_popover .gradient-color-bin a",
                content: "Delete step",
                run: "click",
            },
            checkGradient:
                "linear-gradient(135deg, rgb(203, 94, 238) 0%, rgb(75, 225, 236) 100%)",
        }),
        ...updateAndCheckCustomGradient({
            updateStep: {
                trigger: ".o_popover input[name='angle']",
                content: "Change angle",
                run: "edit 50 && click .o_color_picker_inputs",
            },
            checkGradient:
                "linear-gradient(50deg, rgb(203, 94, 238) 0%, rgb(75, 225, 236) 100%)",
        }),
        ...updateAndCheckCustomGradient({
            updateStep: {
                trigger: ".o_popover button:contains('Radial')",
                content: "Switch to Radial",
                run: "click",
            },
            checkGradient:
                "radial-gradient(circle closest-side at 25% 25%, rgb(203, 94, 238) 0%, rgb(75, 225, 236) 100%)",
        }),
        ...updateAndCheckCustomGradient({
            updateStep: {
                trigger: ".o_popover input[name='positionX']",
                content: "Change X position",
                run: "edit 33 && click .o_color_picker_inputs",
            },
            checkGradient:
                "radial-gradient(circle closest-side at 33% 25%, rgb(203, 94, 238) 0%, rgb(75, 225, 236) 100%)",
        }),
        ...updateAndCheckCustomGradient({
            updateStep: {
                trigger: ".o_popover input[name='positionY']",
                content: "Change Y position",
                run: "edit 75 && click .o_color_picker_inputs",
            },
            checkGradient:
                "radial-gradient(circle closest-side at 33% 75%, rgb(203, 94, 238) 0%, rgb(75, 225, 236) 100%)",
        }),
        ...updateAndCheckCustomGradient({
            updateStep: {
                trigger: ".o_popover button[title='Extend to the farthest side']",
                content: "Change color spread size",
                run: "click",
            },
            checkGradient:
                "radial-gradient(circle farthest-side at 33% 75%, rgb(203, 94, 238) 0%, rgb(75, 225, 236) 100%)",
        }),
        {
            trigger: `.o_colorpicker_sections button[data-color="${gradients[0]}"]`,
            content: `Revert to predefiend gradient ${gradients[0]}`,
            run: "click",
        },

        ...checkAndUpdateBackgroundColor({
            checkCC: "o_cc1",
            checkGradient: gradients[0],
            checkNoGradient: gradients[1],
            changeType: "bg",
            change: backgroundColors[1].code,
            finalSelector: `:iframe .${snippets[0].id}.o_cc1.bg-${backgroundColors[1].code}[style^="background-image: url("]:not([style*="${gradients[0]}"])`,
        }),

        ...checkAndUpdateBackgroundColor({
            checkCC: "o_cc1",
            checkBg: backgroundColors[1].code,
            checkNoGradient: gradients[0],
            changeType: "gradient",
            change: gradients[1],
            finalSelector: `:iframe .${snippets[0].id}.o_cc1:not(.bg-${backgroundColors[1].code})`,
            finalRun() {
                const parts = backgroundImageCssToParts(
                    getComputedStyle(this.anchor)["background-image"],
                );
                if (!parts.url || !parts.url.startsWith("url(")) {
                    throw new Error(
                        "The image should have been kept when re-adding the gradient",
                    );
                }
                if (parts.gradient !== gradients[1]) {
                    throw new Error("The gradient should have been re-added");
                }
            },
        }),

        ...checkAndUpdateBackgroundColor({
            checkCC: "o_cc1",
            checkNoBg: backgroundColors[1].code,
            checkGradient: gradients[1],
        }),
        {
            trigger: ".o_popover button[title='Reset']",
            content: "Click on the None button of the color palette",
            run: "click",
        },
        {
            trigger: `:iframe .${snippets[0].id}:not(.o_cc1):not([style*="${gradients[1]}"])[style^="background-image: url("]`,
            content:
                "All color classes and properties should have been removed and image should still be applied",
        },
    ],
);
