import {
    addBuilderOption,
    dummyBase64Img,
    setupHTMLBuilder,
} from "@html_builder/../tests/helpers";
import { BackgroundOption } from "@html_builder/plugins/background_option/background_option";
import { expect, test, describe } from "@odoo/hoot";
import { queryOne, waitFor } from "@odoo/hoot-dom";
import { contains, onRpc } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

// `.oe_img_bg` and its `o_bg_img_opt_repeat` variant are styled in
// `html_editor/static/src/scss/html_editor.common.scss`, which the builder
// iframe bundle does not carry in tests. The two rules the position option
// actually reads are injected here so the test does not depend on which
// stylesheet the harness happens to load.
const bgRepeatStyle = `
    .oe_img_bg { background-repeat: no-repeat; }
    .oe_img_bg.o_bg_img_opt_repeat { background-repeat: repeat !important; }
`;

/**
 * The background options are mounted by `website` in production, so the test
 * registers them itself. Every prop gets a default because an option component
 * is instantiated without props.
 */
function addBackgroundOption() {
    // The image filter and format rows fetch the image they are given; the
    // background layers here are fixtures, not real attachments.
    onRpc("/html_editor/get_image_info", () => ({}));
    addBuilderOption(
        class extends BackgroundOption {
            static selector = ".test-options-target";
            static props = {
                ...BackgroundOption.props,
                withColors: { type: Boolean, optional: true },
                withImages: { type: Boolean, optional: true },
                withColorCombinations: { type: Boolean, optional: true },
            };
            static defaultProps = {
                withColors: false,
                withImages: true,
                withColorCombinations: false,
                withShapes: false,
            };
        }
    );
}

// A base64 source keeps the image rows from fetching anything, which is not
// what these tests are about.
const twoLayerBackground = `background-image: url('${dummyBase64Img}'), linear-gradient(rgb(255, 0, 0), rgb(0, 0, 255));`;

test("'Repeat pattern' sizes the image layer only, leaving the gradient covering", async () => {
    addBackgroundOption();
    await setupHTMLBuilder(
        `<div class="test-options-target oe_img_bg" style="${twoLayerBackground} background-size: cover;">b</div>`,
        { styleContent: bgRepeatStyle }
    );
    await contains(":iframe .test-options-target").click();
    await waitFor("[data-label='Position'] .dropdown");
    expect("[data-label='Position'] .dropdown").toHaveText("Cover");

    await contains("[data-label='Position'] .dropdown").click();
    await contains(".o-overlay-item [data-action-value='repeat-pattern']").click();

    // The image layer takes the pattern size; the gradient behind it keeps
    // covering instead of tiling along with it.
    const layers = queryOne(":iframe .test-options-target")
        .style.backgroundSize.split(",")
        .map((layer) => layer.trim());
    expect(layers).toHaveLength(2);
    expect(layers[0]).toMatch(/^100px/);
    expect(layers.at(-1)).toBe("cover");
    expect("[data-label='Position'] .dropdown").toHaveText("Repeat pattern");
});

test("the size inputs read the image layer of a multi-layer background", async () => {
    addBackgroundOption();
    await setupHTMLBuilder(
        `<div class="test-options-target oe_img_bg o_bg_img_opt_repeat" style="${twoLayerBackground} background-size: 300px auto, cover;">b</div>`,
        { styleContent: bgRepeatStyle }
    );
    await contains(":iframe .test-options-target").click();

    expect(`[data-action-id='setBackgroundSize'][data-action-param='width'] input`).toHaveValue(
        "300"
    );
    expect(`[data-action-id='setBackgroundSize'][data-action-param='height'] input`).toHaveValue("");
});

test("removing the background image stops the gradient from repeating", async () => {
    addBackgroundOption();
    await setupHTMLBuilder(
        `<div class="test-options-target oe_img_bg o_bg_img_opt_repeat" style="${twoLayerBackground} background-size: 100px, cover;">b</div>`,
        { styleContent: bgRepeatStyle }
    );
    await contains(":iframe .test-options-target").click();
    await contains("[data-action-id='removeBgImage']").click();

    expect(":iframe .test-options-target").not.toHaveClass("o_bg_img_opt_repeat");
    expect(queryOne(":iframe .test-options-target").style.backgroundSize).toBe("");
});

test("the button that removes the background image warns in red", async () => {
    addBackgroundOption();
    await setupHTMLBuilder(
        `<div class="test-options-target oe_img_bg" style="${twoLayerBackground}">b</div>`,
        { styleContent: bgRepeatStyle }
    );
    await contains(":iframe .test-options-target").click();
    await waitFor("[data-action-id='removeBgImage']");

    // The other destructive builder buttons already carry this: the snippet
    // trash in `option_container.xml` and "Reset shape" in
    // `image_shape_option.xml`.
    expect("[data-action-id='removeBgImage']").toHaveClass("btn-danger-color-hover");
});
