import { expect, test } from "@odoo/hoot";
import { contains, onRpc } from "@web/../tests/web_test_helpers";
import {
    defineWebsiteModels,
    setupWebsiteBuilderWithSnippet,
} from "@website/../tests/builder/website_helpers";

defineWebsiteModels();

test.skip("alert message displayed if floating blocks has no cards", async () => {
    await setupWebsiteBuilderWithSnippet("s_floating_blocks");
    await contains(":iframe .s_floating_blocks_block").click();
    await contains(
        ".options-container[data-container-title='Card'] .oe_snippet_remove",
    ).click();
    await contains(":iframe .s_floating_blocks_block").click();
    await contains(
        ".options-container[data-container-title='Card'] .oe_snippet_remove",
    ).click();
    await contains(":iframe .s_floating_blocks_block").click();
    await contains(
        ".options-container[data-container-title='Card'] .oe_snippet_remove",
    ).click();
    expect(":iframe .s_floating_blocks_alert_empty").toHaveCount(1);
    expect(":iframe .s_floating_blocks_alert_empty").toBeVisible();
});

test.skip("floating blocks snippet are not removed on save even if empty", async () => {
    const resultSave = [];
    onRpc("ir.ui.view", "save", ({ args }) => {
        resultSave.push(args[1]);
        return true;
    });
    await setupWebsiteBuilderWithSnippet("s_floating_blocks");
    await contains(":iframe .s_floating_blocks_block").click();
    await contains(
        ".options-container[data-container-title='Card'] .oe_snippet_remove",
    ).click();
    await contains(":iframe .s_floating_blocks_block").click();
    await contains(
        ".options-container[data-container-title='Card'] .oe_snippet_remove",
    ).click();
    await contains(":iframe .s_floating_blocks_block").click();
    await contains(
        ".options-container[data-container-title='Card'] .oe_snippet_remove",
    ).click();
    await contains(".o-snippets-top-actions button:contains(Save)").click();
    expect(resultSave[0]).toInclude("s_floating_blocks");
});
