import { getContent } from "@html_editor/../tests/_helpers/selection";
import {
    insertText,
    simulateArrowKeyPress,
    splitBlock,
} from "@html_editor/../tests/_helpers/user_actions";
import { expect, test } from "@odoo/hoot";
import {
    animationFrame,
    click,
    press,
    queryOne,
    setInputRange,
    waitFor,
} from "@odoo/hoot-dom";
import { tick } from "@odoo/hoot-mock";
import { contains } from "@web/../tests/web_test_helpers";
import {
    defineWebsiteModels,
    setupWebsiteBuilder,
    setupWebsiteBuilderWithSnippet,
} from "@website/../tests/builder/website_helpers";

defineWebsiteModels();

test("set card width", async () => {
    await setupWebsiteBuilderWithSnippet("s_card");
    await contains(":iframe .s_card").click();
    await waitFor("[data-action-id='setCardWidth']");
    expect("[data-action-id='setCardWidth']").toHaveCount(1);
    expect(queryOne(":iframe .s_card").style.maxWidth).toBeEmpty();
    expect("[data-action-id='setCardWidth'] input").toHaveValue(100);

    await setInputRange("[data-action-id='setCardWidth'] input", 50);
    await animationFrame();
    expect(":iframe .s_card").toHaveStyle({ maxWidth: "50%" });
});

test("set card alignment", async () => {
    await setupWebsiteBuilderWithSnippet("s_card");
    await contains(":iframe .s_card").click();
    await waitFor("[data-action-id='setCardWidth'] input");
    expect("[data-action-id='setCardWidth'] input").toHaveValue(100);
    expect("[data-label='Card Width'] + [data-label='Alignment']").toHaveCount(0);

    await setInputRange("[data-action-id='setCardWidth'] input", 50);
    await waitFor("[data-label='Card Width'] + [data-label='Alignment']");
    expect("[data-label='Card Width'] + [data-label='Alignment']").toHaveCount(1);

    expect(":iframe .s_card").not.toHaveClass(["me-auto", "mx-auto", "ms-auto"]);
    expect(
        "[data-label='Card Width'] + [data-label='Alignment'] button[title='Left']",
    ).toHaveClass("active");

    await click(
        "[data-label='Card Width'] + [data-label='Alignment'] button[title='Center']",
    );
    await animationFrame();
    expect(":iframe .s_card").toHaveClass("mx-auto");

    await click(
        "[data-label='Card Width'] + [data-label='Alignment'] button[title='Right']",
    );
    await animationFrame();
    expect(":iframe .s_card").toHaveClass("ms-auto");

    await click(
        "[data-label='Card Width'] + [data-label='Alignment'] button[title='Left']",
    );
    await animationFrame();
    expect(":iframe .s_card").toHaveClass("me-auto");
});

test("remove/add cover image", async () => {
    await setupWebsiteBuilderWithSnippet("s_card");
    await contains(":iframe .s_card").click();
    await waitFor("[data-action-id='removeCoverImage']");
    expect("[data-action-id='removeCoverImage']").toHaveCount(1);
    expect("[data-action-id='addCoverImage']").toHaveCount(0);
    await click("[data-action-id='removeCoverImage']");
    expect(":iframe .s_card .o_card_img_wrapper").toHaveCount(0);
    expect(":iframe .s_card").not.toHaveClass("o_card_img_top");
    await waitFor("[data-action-id='addCoverImage']");
    expect("[data-action-id='removeCoverImage']").toHaveCount(0);
    expect("[data-action-id='addCoverImage']").toHaveCount(1);
    await click("[data-action-id='addCoverImage']");
    expect(":iframe .s_card .o_card_img_wrapper").toHaveCount(1);
});

const nestedCardsWithOneCover = `
    <div class="s_card card outer_card o_draggable" data-snippet="s_card" data-name="Card">
        <div class="card-body">
            <div class="s_card o_card_img_top card inner_card" data-snippet="s_card" data-name="Card">
                <figure class="o_card_img_wrapper mb-0 ratio ratio-16x9">
                    <img class="o_card_img card-img-top" src="/web/image/website.s_card_default_image_1" alt="" loading="lazy" data-mimetype="image/jpeg">
                </figure>
                <div class="card-body"/>
            </div>
        </div>
    </div>
`;

test("cover image options only appear on the right card when two of them are nested", async () => {
    await setupWebsiteBuilder(nestedCardsWithOneCover);
    await contains(":iframe .outer_card").click();
    expect("[data-action-id='setCoverImagePosition']").toHaveCount(0);
    expect("[data-action-id='removeCoverImage']").toHaveCount(0);

    await contains(":iframe .inner_card").click();
    expect("[data-action-id='setCoverImagePosition']").toHaveCount(4);
    expect("[data-action-id='removeCoverImage']").toHaveCount(1);
});

test("set cover image position", async () => {
    await setupWebsiteBuilderWithSnippet("s_card");
    await contains(":iframe .s_card").click();
    await waitFor("[data-action-id='setCoverImagePosition']");
    expect(":iframe .s_card").toHaveClass("o_card_img_top");
    expect(":iframe .s_card .o_card_img").toHaveClass("card-img-top");
    expect("[data-action-id='setCoverImagePosition'][title='Top']").toHaveClass(
        "active",
    );

    await click("[data-action-id='setCoverImagePosition'][title='Left']");
    await waitFor("[data-action-id='setCoverImagePosition'][title='Left'].active");
    expect(":iframe .s_card").toHaveClass(["o_card_img_horizontal", "flex-lg-row"]);
    expect(":iframe .s_card .o_card_img").toHaveClass("rounded-start");

    await click("[data-action-id='setCoverImagePosition'][title='Right']");
    await waitFor("[data-action-id='setCoverImagePosition'][title='Right'].active");
    expect(":iframe .s_card").toHaveClass([
        "o_card_img_horizontal",
        "flex-lg-row-reverse",
    ]);
    expect(":iframe .s_card .o_card_img").toHaveClass("rounded-end");

    await click("[data-action-id='setCoverImagePosition'][title='Bottom']");
    await waitFor("[data-action-id='setCoverImagePosition'][title='Bottom'].active");
    expect(":iframe .s_card").toHaveClass(["o_card_img_bottom", "flex-column-reverse"]);
    expect(":iframe .s_card").not.toHaveClass([
        "o_card_img_horizontal",
        "flex-lg-row",
        "flex-lg-row-reverse",
    ]);
    expect(":iframe .s_card .o_card_img").toHaveClass("card-img-bottom");

    await click("[data-action-id='removeCoverImage']");
    await waitFor("[data-action-id='addCoverImage']");
    expect(":iframe .s_card").not.toHaveClass([
        "o_card_img_top",
        "o_card_img_bottom",
        "o_card_img_horizontal",
        "flex-lg-row",
        "flex-lg-row-reverse",
        "flex-column-reverse",
    ]);
    expect("[data-action-id='setCoverImagePosition']").toHaveCount(0);
});

async function openRatioDropdownMenu() {
    click("[data-label='Ratio'] .dropdown");
    await waitFor(".popover.dropdown-menu");
}

test("set cover image ratio", async () => {
    await setupWebsiteBuilderWithSnippet("s_card");
    await contains(":iframe .s_card").click();

    expect(":iframe .s_card .o_card_img_wrapper").toHaveClass(["ratio", "ratio-16x9"]);
    await waitFor("[data-label='Ratio'] ");
    expect("[data-label='Ratio'] .dropdown").toHaveText("Wide - 16/9");

    await openRatioDropdownMenu();
    await click(".dropdown-menu [data-class-action=''");
    await animationFrame();
    expect(":iframe .s_card .o_card_img_wrapper").not.toHaveClass("ratio");

    for (const ratioClass of ["ratio-1x1", "ratio-4x3", "ratio-16x9", "ratio-21x9"]) {
        await openRatioDropdownMenu();
        await click(`.dropdown-menu [data-class-action='ratio ${ratioClass}']`);
        await animationFrame();
        expect(":iframe .s_card .o_card_img_wrapper").toHaveClass([
            "ratio",
            ratioClass,
        ]);
    }

    await openRatioDropdownMenu();
    await click(".dropdown-menu [data-class-action='ratio o_card_img_ratio_custom']");
    await waitFor("[data-label='Custom Ratio'] input[type='range']");
    await setInputRange("[data-label='Custom Ratio'] input[type='range']", 60);
    await animationFrame();
    expect(":iframe .s_card .o_card_img_wrapper").toHaveClass(
        "o_card_img_ratio_custom",
    );
    expect(":iframe .s_card").toHaveStyle({ "--card-img-aspect-ratio": "60%" });
});

test("ratios supported for vertical images", async () => {
    const verticalRatioClasses = [
        "ratio-1x1",
        "ratio-4x3",
        "ratio-16x9",
        "ratio-21x9",
        "o_card_img_ratio_custom",
    ];
    await setupWebsiteBuilderWithSnippet("s_card");
    await contains(":iframe .s_card").click();
    await waitFor("[data-label='Ratio'] ");
    await openRatioDropdownMenu();
    expect(":iframe .s_card").toHaveClass("o_card_img_top");
    expect(`.dropdown-menu [data-class-action='']`).toHaveCount(1);
    for (const ratioClass of verticalRatioClasses) {
        expect(`.dropdown-menu [data-class-action='ratio ${ratioClass}']`).toHaveCount(
            1,
        );
    }
    await click("[data-action-id='setCoverImagePosition'][title='Bottom']");
    await waitFor("[data-action-id='setCoverImagePosition'][title='Bottom'].active");
    await openRatioDropdownMenu();
    expect(":iframe .s_card").toHaveClass("o_card_img_bottom");
    expect(`.dropdown-menu [data-class-action='']`).toHaveCount(1);
    for (const ratioClass of verticalRatioClasses) {
        expect(`.dropdown-menu [data-class-action='ratio ${ratioClass}']`).toHaveCount(
            1,
        );
    }
    await click("[data-action-id='setCoverImagePosition'][title='Left']");
    await waitFor("[data-action-id='setCoverImagePosition'][title='Left'].active");
    expect(":iframe .s_card").toHaveClass(["o_card_img_horizontal", "flex-lg-row"]);
    await openRatioDropdownMenu();
    expect(`.dropdown-menu [data-class-action='']`).toHaveCount(1);
    expect(`.dropdown-menu [data-class-action='ratio ratio-1x1']`).toHaveCount(1);
    for (const ratioClass of [
        "ratio-4x3",
        "ratio-16x9",
        "ratio-21x9",
        "o_card_img_ratio_custom",
    ]) {
        expect(`.dropdown-menu [data-class-action='ratio ${ratioClass}']`).toHaveCount(
            0,
        );
    }
});

test("set cover image width", async () => {
    await setupWebsiteBuilderWithSnippet("s_card");
    await contains(":iframe .s_card").click();

    await waitFor("[data-action-id='setCoverImagePosition']");
    expect("[data-label='Width']").toHaveCount(0);
    await click("[data-action-id='setCoverImagePosition'][title='Bottom']");
    await waitFor("[data-action-id='setCoverImagePosition'][title='Bottom'].active");
    expect("[data-label='Width']").toHaveCount(0);
    await click("[data-action-id='setCoverImagePosition'][title='Left']");
    await waitFor("[data-label='Width']");
    expect("[data-label='Width']").toHaveCount(1);
    await setInputRange("[data-label='Width'] input", 25);
    await animationFrame();
    const cardImageWidthValue =
        queryOne(":iframe .s_card").style.getPropertyValue("--card-img-size-h");
    expect(parseFloat(cardImageWidthValue)).toBeWithin(24.9, 25.1);
});

test("cover image set to wide aspect ratio can be vertically aligned", async () => {
    await setupWebsiteBuilderWithSnippet("s_card");
    await contains(":iframe .s_card").click();
    await waitFor("[data-action-id='alignCoverImage']");
    expect("[data-label='Alignment'] [data-action-id='alignCoverImage'").toHaveCount(1);
    await setInputRange("[data-action-id='alignCoverImage'] input", 50);
    await animationFrame();
    expect(":iframe .s_card .o_card_img_wrapper").toHaveClass("o_card_img_adjust_v");
    expect(":iframe .s_card").toHaveStyle({ "--card-img-ratio-align": "50%" });
});

const nestedCardsWithTwoCovers = `
    <div class="s_card o_card_img_top card outer_card o_draggable" data-snippet="s_card" data-name="Card">
        <figure class="o_card_img_wrapper mb-0 ratio ratio-16x9">
            <img class="o_card_img card-img-top" src="/web/image/website.s_card_default_image_1" alt="" loading="lazy" data-mimetype="image/jpeg">
        </figure>
        <div class="card-body">
            <div class="s_card o_card_img_top card inner_card" data-snippet="s_card" data-name="Card">
                <figure class="o_card_img_wrapper mb-0 ratio ratio-16x9">
                    <img class="o_card_img card-img-top" src="/web/image/website.s_card_default_image_1" alt="" loading="lazy" data-mimetype="image/jpeg">
                </figure>
                <div class="card-body"/>
            </div>
        </div>
    </div>
`;

test("cover image ratio option only act on the right card when two of them are nested", async () => {
    await setupWebsiteBuilder(nestedCardsWithTwoCovers);
    expect(":iframe figure.o_card_img_ratio_custom").toHaveCount(0);

    await contains(":iframe .outer_card").click();
    await waitFor("[data-label='Ratio'] ");
    await openRatioDropdownMenu();
    await click(".dropdown-menu [data-class-action='ratio o_card_img_ratio_custom']");
    await waitFor("[data-label='Custom Ratio'] input[type='range']");
    expect(":iframe figure.o_card_img_ratio_custom").toHaveCount(1);
});

test.tags("desktop");
test("navigate between cards with keyboard", async () => {
    const { getEditor } = await setupWebsiteBuilderWithSnippet("s_cards_grid");
    const editor = getEditor();
    const h2El = await waitFor(":iframe h2");
    const rowEl = await waitFor(":iframe div.row");
    await contains(":iframe .s_cards_grid :contains()").click();
    await simulateArrowKeyPress(editor, "ArrowDown");
    await tick();
    await simulateArrowKeyPress(editor, "ArrowLeft");
    await tick();
    expect(getContent(h2El)).toMatch(/^.+\[\]$/);
    splitBlock(editor);
    expect(":iframe p[data-selection-placeholder]").toHaveCount(0);
    await insertText(editor, "/table");
    await press("Enter");
    await waitFor(".o-we-tablepicker");
    await press("Enter");
    const tableEl = await waitFor(":iframe table");
    expect(":iframe p[data-selection-placeholder]").toHaveCount(0);

    await insertText(editor, "1");
    await animationFrame();
    expect(getContent(tableEl)).toMatch(/>1\[\]<\/p>/);
    await simulateArrowKeyPress(editor, "ArrowDown");
    await animationFrame();
    expect(getContent(tableEl)).toMatch(/>1<\/p>/);
    await insertText(editor, "2");
    await animationFrame();
    expect(getContent(tableEl)).toMatch(/>2\[\]<\/p>/);
    await simulateArrowKeyPress(editor, "ArrowDown");
    await animationFrame();
    expect(getContent(tableEl)).toMatch(/>2<\/p>/);
    await insertText(editor, "3");
    await animationFrame();
    expect(getContent(tableEl)).toMatch(/>3\[\]<\/p>/);
    await simulateArrowKeyPress(editor, "ArrowDown");
    await animationFrame();
    expect(getContent(tableEl)).toMatch(/>3<\/p>/);
    expect(":iframe p[data-selection-placeholder]").toHaveCount(0);
    await simulateArrowKeyPress(editor, "ArrowDown");
    await animationFrame();
    expect(":iframe p[data-selection-placeholder]").toHaveCount(0);
    expect(getContent(rowEl)).toMatch(/>Qu\[\]ality/);

    await simulateArrowKeyPress(editor, "ArrowDown");
    await animationFrame();
    expect(getContent(rowEl)).toMatch(/>We\[\] provide/);

    await simulateArrowKeyPress(editor, "ArrowDown");
    await animationFrame();
    expect(getContent(rowEl)).toMatch(/>Ex\[\]pertise/);

    await simulateArrowKeyPress(editor, "ArrowUp");
    await animationFrame();
    expect(getContent(rowEl)).toMatch(/>We\[\] provide/);

    await simulateArrowKeyPress(editor, "ArrowDown");
    await animationFrame();
    await simulateArrowKeyPress(editor, "ArrowLeft");
    await animationFrame();
    await simulateArrowKeyPress(editor, "ArrowLeft");
    await animationFrame();
    expect(getContent(rowEl)).toMatch(/>\[\]Expertise/);

    await simulateArrowKeyPress(editor, "ArrowLeft");
    await animationFrame();
    expect(getContent(rowEl)).toMatch(/finish.\[\]<\/p>/);

    await simulateArrowKeyPress(editor, "ArrowRight");
    await animationFrame();
    expect(getContent(rowEl)).toMatch(/>\[\]Expertise/);
});
