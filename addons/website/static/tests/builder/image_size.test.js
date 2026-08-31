import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-dom";
import { contains } from "@web/../tests/web_test_helpers";

import {
    testGifImg,
    testGifImgSrc,
    testImg,
    testImgSrc,
} from "./image_test_helpers.js";
import { defineWebsiteModels, setupWebsiteBuilder } from "./website_helpers.js";

defineWebsiteModels();

test("the image should show its size", async () => {
    const { waitSidebarUpdated } = await setupWebsiteBuilder(`
        <div class="test-options-target">
            ${testImg}
        </div>
    `);
    await contains(":iframe .test-options-target img").click();
    await waitSidebarUpdated();
    const selector = `[data-container-title="Image"] [title="Size"]`;
    const size = parseFloat(document.querySelector(selector).innerHTML);
    expectAround(size, 22.8);
});

test("the background image should show its size", async () => {
    const { waitSidebarUpdated } = await setupWebsiteBuilder(`
        <div class="test-options-target">
            <section style="background-image: url(${testImgSrc});">text</section>
        </div>
    `);
    await contains(":iframe .test-options-target section").click();
    await waitSidebarUpdated();
    const selector = `[data-label="Image"] [title="Size"]`;
    const size = parseFloat(document.querySelector(selector).innerHTML);
    expectAround(size, 22.8);
});

function expectAround(value, expected, delta = 0.2) {
    expect(value).toBeGreaterThan(expected - delta);
    expect(value).toBeLessThan(expected + delta);
}

test("the GIF image should show its size", async () => {
    const { waitSidebarUpdated } = await setupWebsiteBuilder(`
        <div class="test-options-target">
            ${testGifImg}
        </div>
    `);
    await contains(":iframe .test-options-target img").click();
    await waitSidebarUpdated();
    const selector = `[data-container-title="Image"] [title="Size"]`;
    const size = parseFloat(document.querySelector(selector).innerHTML);
    expectAround(size, 325.2);
});

test("the GIF background image should show its size", async () => {
    const { waitSidebarUpdated } = await setupWebsiteBuilder(`
        <div class="test-options-target">
            <section style="background-image: url(${testGifImgSrc});">text</section>
        </div>
    `);
    await contains(":iframe .test-options-target section").click();
    await waitSidebarUpdated();
    const selector = `[data-label="Image"] [title="Size"]`;
    const size = parseFloat(document.querySelector(selector).innerHTML);
    expectAround(size, 325.2);
});

const SLIDER = ".options-container [data-action-id='mediaSizeSlider'] input";
const TEXT = ".options-container [data-action-id='mediaSizeText'] input";
const TEXT_UNIT = ".options-container [data-action-id='mediaSizeText'] .o-hb-input-field-unit";
const AUTO = ".options-container button[data-action-id='setMediaSizeAuto']";

/**
 * The three controls agree with one another and with the element: unset means
 * the Auto button is on, the text input shows its placeholder and no unit, and
 * the slider parks at 99%.
 */
function expectUnsetSize() {
    expect(SLIDER).toHaveValue(99);
    expect(TEXT).toHaveValue("");
    expect(TEXT_UNIT).toHaveCount(0);
    expect(AUTO).toHaveClass("active");
}

test("an image can be resized by slider, by typing a percentage, and back to auto", async () => {
    const { waitSidebarUpdated } = await setupWebsiteBuilder(`
        <div class="test-options-target">
            ${testImg}
        </div>
    `);
    await contains(":iframe .test-options-target img").click();
    await waitSidebarUpdated();
    expectUnsetSize();

    // Typed values are clamped to the 5-100 the option offers.
    await contains(TEXT).edit("3");
    await animationFrame();
    expect(":iframe .test-options-target img").toHaveStyle(
        { width: "5% !important" },
        { inline: true }
    );

    await contains(TEXT).edit("110");
    await animationFrame();
    expect(":iframe .test-options-target img").toHaveStyle(
        { width: "100% !important" },
        { inline: true }
    );

    // A free percentage, which the four presets could not express.
    await contains(":iframe .test-options-target img").click();
    await waitSidebarUpdated();
    await contains(TEXT).edit("37", { confirm: "enter" });
    await animationFrame();
    expect(":iframe .test-options-target img").toHaveStyle(
        { width: "37% !important" },
        { inline: true }
    );

    // The slider writes the same style and the text input follows it.
    await contains(":iframe .test-options-target img").click();
    await waitSidebarUpdated();
    await contains(SLIDER).edit("65");
    await waitSidebarUpdated();
    expect(":iframe .test-options-target img").toHaveStyle(
        { width: "65% !important" },
        { inline: true }
    );
    expect(TEXT).toHaveValue("65");
    expect(TEXT_UNIT).toHaveCount(1);
    expect(AUTO).not.toHaveClass("active");

    // Clearing the input is the same as asking for auto.
    await contains(":iframe .test-options-target img").click();
    await waitSidebarUpdated();
    await contains(TEXT).clear({ confirm: "enter" });
    await waitSidebarUpdated();
    expect(":iframe .test-options-target img").toHaveStyle(
        { width: "auto !important" },
        { inline: true }
    );
    expectUnsetSize();
});

test("a video can be resized at all", async () => {
    // Before this option a video had no size control of any kind.
    const { waitSidebarUpdated } = await setupWebsiteBuilder(`
        <figure class="figure">
            <div data-oe-expression="//www.youtube.com/embed/G8b4UZIcTfg?rel=0&amp;autoplay=0" class="figure-img media_iframe_video">
                <iframe src="//www.youtube.com/embed/G8b4UZIcTfg?rel=0&amp;autoplay=0"></iframe>
            </div>
        </figure>
    `);
    await contains(":iframe .media_iframe_video").click();
    await waitSidebarUpdated();
    expectUnsetSize();

    await contains(TEXT).edit("50", { confirm: "enter" });
    await animationFrame();
    expect(":iframe .media_iframe_video").toHaveStyle(
        { width: "50% !important" },
        { inline: true }
    );

    await contains(":iframe .media_iframe_video").click();
    await waitSidebarUpdated();
    await contains(AUTO).click();
    await animationFrame();
    expect(":iframe .media_iframe_video").toHaveStyle(
        { width: "auto !important" },
        { inline: true }
    );
    expectUnsetSize();
});

test("the size option stays out of grid mode", async () => {
    const { waitSidebarUpdated } = await setupWebsiteBuilder(`
        <div class="container">
            <div class="row o_grid_mode" data-row-count="6">
                <div class="video-test o_grid_item g-height-5 g-col-lg-5 col-lg-5" data-name="Block" style="z-index: 1; grid-area: 2 / 1 / 7 / 6;">
                    <div data-oe-expression="//www.youtube.com/embed/G8b4UZIcTfg?rel=0&amp;autoplay=0" class="mx-auto media_iframe_video">
                        <iframe src="//www.youtube.com/embed/G8b4UZIcTfg?rel=0&amp;autoplay=0"></iframe>
                    </div>
                </div>
            </div>
        </div>
    `);
    await contains(":iframe .video-test .media_iframe_video").click();
    await waitSidebarUpdated();
    expect(".options-container [data-label='Size']").toHaveCount(0);
});
