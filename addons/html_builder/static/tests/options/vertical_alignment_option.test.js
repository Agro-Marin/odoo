import { setupHTMLBuilder } from "@html_builder/../tests/helpers";
import { describe, expect, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import { contains } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

const SNIPPETS = ["s_key_images", "s_cards_soft", "s_cards_grid"];

const twoColumns = (snippet) =>
    `<section class="${snippet}"><div class="row">
        <div class="col-lg-6"><p>one</p></div>
        <div class="col-lg-6"><p>two</p></div>
    </div></section>`;

test("the card snippets offer vertical alignment", async () => {
    await setupHTMLBuilder(SNIPPETS.map(twoColumns).join(""));
    for (const snippet of SNIPPETS) {
        await contains(`:iframe .${snippet}`).click();
        const rowEl = queryOne(`:iframe .${snippet} .row`);
        for (const alignment of ["start", "center", "end", "stretch"]) {
            await contains(`[data-action-param='align-items-${alignment}']`).click();
            expect(rowEl).toHaveClass(`align-items-${alignment}`);
        }
    }
});

test("the vertical alignment row explains itself", async () => {
    await setupHTMLBuilder(twoColumns("s_key_images"));
    await contains(":iframe .s_key_images").click();
    expect("[data-label='Vert. Alignment']").toHaveCount(1);
    expect("[data-label='Vert. Alignment'] .fa-question").toHaveCount(1);
});

test("a card snippet is upgraded on setup so stretch has something to stretch", async () => {
    await setupHTMLBuilder(
        `<section class="s_cards_grid"><div class="row">
            <div data-name="Card" class="col-lg-6">
                <div class="s_card card"><img class="o_card_img" src="/web/static/img/placeholder.png"/></div>
            </div>
        </div></section>`
    );
    expect(":iframe .s_cards_grid").toHaveAttribute("data-vxml", "001");
    expect(":iframe .s_cards_grid .row").toHaveClass("align-items-start");
    expect(":iframe .s_cards_grid .s_card").toHaveClass("h-100");
    expect(":iframe .s_cards_grid .col-lg-6").toHaveClass("d-flex");
    expect(":iframe .s_cards_grid .o_card_img").toHaveClass("object-fit-cover");
});
