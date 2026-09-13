import { expect, test } from "@odoo/hoot";
import { contains } from "@web/../tests/web_test_helpers";
import {
    defineWebsiteModels,
    setupWebsiteBuilder,
} from "@website/../tests/builder/website_helpers";

defineWebsiteModels();

const instagramTemplate = `
    <section class="s_instagram_page" data-snippet="s_instagram_page" data-name="Instagram Page"
        data-instagram-page="odoo.official" style="min-height: 100px;">
        <div class="o_container_small o_instagram_container o_not_editable"></div>
    </section>
`;

test("pasting an Instagram URL stores the page name", async () => {
    await setupWebsiteBuilder(instagramTemplate);
    await contains(":iframe .s_instagram_page").click();
    await contains(".hb-row[data-label='Instagram Page'] input").edit(
        "https://www.instagram.com/my.page/",
    );
    expect(":iframe .s_instagram_page").toHaveAttribute(
        "data-instagram-page",
        "my.page",
    );
});

test("typing a page name stores it as is", async () => {
    await setupWebsiteBuilder(instagramTemplate);
    await contains(":iframe .s_instagram_page").click();
    await contains(".hb-row[data-label='Instagram Page'] input").edit("my.page");
    expect(":iframe .s_instagram_page").toHaveAttribute(
        "data-instagram-page",
        "my.page",
    );
});
