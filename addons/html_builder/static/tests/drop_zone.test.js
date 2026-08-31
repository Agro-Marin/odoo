import {
    getSnippetStructure,
    setupHTMLBuilder,
    waitForEndOfOperation,
    confirmAddSnippet,
} from "@html_builder/../tests/helpers";
import { describe, expect, test } from "@odoo/hoot";
import { advanceTime, queryOne } from "@odoo/hoot-dom";
import { contains } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

const dropzone = (hovered = false) => {
    const highlightClass = hovered ? " o_dropzone_highlighted" : "";
    return `<div class="oe_drop_zone oe_insert${highlightClass}" data-editor-message-default="true" data-editor-message="DRAG BUILDING BLOCKS HERE"></div>`;
};

test("wrapper element has the 'DRAG BUILDING BLOCKS HERE' message", async () => {
    const { contentEl } = await setupHTMLBuilder("");
    expect(contentEl).toHaveAttribute("data-editor-message", "DRAG BUILDING BLOCKS HERE");
});

test("drop beside dropzone inserts the snippet", async () => {
    const { contentEl } = await setupHTMLBuilder();
    const { moveTo, drop } = await contains(
        ".o-snippets-menu #snippet_groups .o_snippet_thumbnail"
    ).drag();
    await moveTo(contentEl.ownerDocument.body);
    // The dropzone is not hovered, so not highlighted.
    expect(contentEl).toHaveInnerHTML(dropzone());
    await drop();
    await confirmAddSnippet();
    expect(".o_add_snippet_dialog").toHaveCount(0);
    await waitForEndOfOperation();
    expect(contentEl)
        .toHaveInnerHTML(`<section class="s_test" data-snippet="s_test" data-name="Test">
    <div class="test_a"></div>
    </section>`);
});

test("snippets cannot be dropped next to elements inside excluded parent", async () => {
    const snippetContent = [
        `<div name="Image" data-oe-thumbnail="image.svg" data-snippet="s_image">
            <img src="/web/image/test.png" data-snippet="s_image" alt="Test Image"/>
        </div>`,
    ];
    const dropzoneSelectors = [
        {
            selector: "img",
            dropNear: "p, h1",
            excludeNearParent: ".second-div",
        },
    ];
    await setupHTMLBuilder(
        `<div class="first-div"><h1>Title</h1><p>Paragraph</p></div>
        <div class="second-div"><h1>Title</h1><p>Paragraph</p></div>`,
        { snippetContent, dropzoneSelectors }
    );

    await contains(".o-snippets-menu .o_snippet_thumbnail[data-snippet='s_image']").drag();
    // Should have 3 dropzones in first-div (not excluded)
    expect(":iframe .first-div .oe_drop_zone").toHaveCount(3);
    // Should have no dropzones in second-div (excluded by excludeNearParent)
    expect(":iframe .second-div .oe_drop_zone").toHaveCount(0);
});

test("a dropped full screen height section is scrolled flush to the top", async () => {
    // Every other snippet is scrolled to with 50px of room above, so the user
    // can see what it landed under. A section whose whole point is to fill the
    // screen must not be, or it demonstrates the opposite of what it claims.
    const fullScreenSection = `<section class="s_test o_full_screen_height" data-snippet="s_test" data-name="Test"><div class="test_a"></div></section>`;
    const { contentEl } = await setupHTMLBuilder(`<section class="filler">Text</section>`, {
        snippets: {
            snippet_groups: [
                '<div name="A" data-oe-thumbnail="a.svg" data-oe-snippet-id="123" data-o-snippet-group="a"><section data-snippet="s_snippet_group"></section></div>',
            ],
            snippet_structure: [
                getSnippetStructure({ name: "Test", groupName: "a", content: fullScreenSection }),
            ],
        },
        // The iframe has to be able to scroll for the offset to be observable,
        // and the body's default 8px margin has to go or it is indistinguishable
        // from a leftover scroll offset.
        styleContent: `body { margin: 0; } .filler { height: 2000px; } .o_full_screen_height { height: 100vh; }`,
    });

    const { moveTo, drop } = await contains(
        ".o-snippets-menu #snippet_groups .o_snippet_thumbnail"
    ).drag();
    await moveTo(contentEl.ownerDocument.body);
    await drop();
    await confirmAddSnippet();
    await waitForEndOfOperation();
    // scrollTo animates over 600ms.
    await advanceTime(700);

    expect(queryOne(":iframe .o_full_screen_height").getBoundingClientRect().top).toBe(0);
});
