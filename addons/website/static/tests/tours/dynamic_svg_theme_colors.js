import {
    changeOption,
    insertSnippet,
    registerWebsitePreviewTour,
} from "@website/js/tours/tour_utils";

const IMG_SELECTOR =
    ":iframe .s_text_image img[src^='/html_editor/shape/illustration/dynamic-svg-test']";

const theme = {};

function readTheme(imgEl) {
    const root = imgEl.ownerDocument.documentElement;
    const style = imgEl.ownerDocument.defaultView.getComputedStyle(root);
    for (const n of [1, 2, 3]) {
        theme[n] = style.getPropertyValue(`--o-color-${n}`).trim();
    }
}

function sameColor(a, b) {
    return String(a).toLowerCase() === String(b).toLowerCase();
}

async function waitForSrcColors(imgEl, expected, errorMessage) {
    for (let attempt = 0; attempt < 50; attempt++) {
        const params = new URL(imgEl.getAttribute("src"), window.location.origin)
            .searchParams;
        if (
            Object.entries(expected).every(([name, value]) =>
                sameColor(params.get(name), value),
            )
        ) {
            return;
        }
        await new Promise((resolve) => setTimeout(resolve, 100));
    }
    throw new Error(`${errorMessage} (src: ${imgEl.getAttribute("src")})`);
}

async function assertSvgColors(imgEl, colors, errorMessage) {
    const response = await fetch(imgEl.src);
    const svg = (await response.text()).toLowerCase();
    if (
        !colors.every((color) => svg.includes(color.toLowerCase())) ||
        !svg.includes("#000000")
    ) {
        throw new Error(errorMessage);
    }
}

registerWebsitePreviewTour(
    "website_dynamic_svg_theme_colors",
    {
        url: "/",
        edition: true,
    },
    () => [
        ...insertSnippet({
            id: "s_text_image",
            name: "Text - Image",
            groupName: "Content",
        }),
        {
            content: "Set the dynamic SVG image",
            trigger: ":iframe .s_text_image img",
            run() {
                readTheme(this.anchor);
                this.anchor.setAttribute(
                    "src",
                    "/html_editor/shape/illustration/dynamic-svg-test" +
                        `?c1=${encodeURIComponent(theme[1])}` +
                        `&c2=${encodeURIComponent(theme[2])}&unique=4a2363`,
                );
            },
        },
        {
            content: "Check the SVG uses theme colors",
            trigger: IMG_SELECTOR,
            async run() {
                await waitForSrcColors(
                    this.anchor,
                    { c1: theme[1], c2: theme[2] },
                    "Dynamic SVG theme colors were not set.",
                );
                await assertSvgColors(
                    this.anchor,
                    [theme[1], theme[2]],
                    "Dynamic SVG theme colors were not applied.",
                );
            },
        },
        {
            content: "Select the dynamic SVG image",
            trigger: IMG_SELECTOR,
            run: "click",
        },
        changeOption("Image", ".o_we_color_preview"),
        {
            content: "Select o-color-3 in the colorpicker",
            trigger: ".o_colorpicker_section button[data-color='o-color-3']",
            run: "click",
        },
        {
            content: "Check the SVG uses the new theme color",
            trigger: IMG_SELECTOR,
            async run() {
                await waitForSrcColors(
                    this.anchor,
                    { c1: "o-color-3", c2: theme[2] },
                    "Dynamic SVG color did not update.",
                );
                await assertSvgColors(
                    this.anchor,
                    [theme[3], theme[2]],
                    "Dynamic SVG color did not update.",
                );
            },
        },
        changeOption("Image", ".o_we_color_preview"),
        {
            content: "Reset the colorpicker",
            trigger: ".o_popover button[title='Reset']",
            run: "click",
        },
        {
            content: "Check the SVG uses the theme colors on reset",
            trigger: IMG_SELECTOR,
            async run() {
                await waitForSrcColors(
                    this.anchor,
                    { c1: theme[1], c2: theme[2] },
                    "Dynamic SVG theme colors were not restored.",
                );
                await assertSvgColors(
                    this.anchor,
                    [theme[1], theme[2]],
                    "Dynamic SVG theme colors were not restored.",
                );
            },
        },
    ],
);
