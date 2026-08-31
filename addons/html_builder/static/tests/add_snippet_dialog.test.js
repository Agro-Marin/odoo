import {
    confirmAddSnippet,
    setupHTMLBuilderWithDummySnippet,
    waitForSnippetDialog,
} from "@html_builder/../tests/helpers";
import { describe, expect, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import { contains } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

const MOBILE_BTN = ".o_add_snippet_dialog button[title='Toggle Mobile Preview']";
const SNIPPET_IFRAME = ".o_add_snippet_dialog iframe.o_add_snippet_iframe";

async function openSnippetDialog() {
    await contains(".o_snippet_thumbnail_area").click();
    await waitForSnippetDialog();
}

test("the mobile preview toggle relays out the blocks, and gives the layout back", async () => {
    await setupHTMLBuilderWithDummySnippet("<h1>Homepage</h1>");
    await openSnippetDialog();
    expect(MOBILE_BTN).toHaveCount(1);

    const iframeDoc = queryOne(SNIPPET_IFRAME).contentDocument;
    expect(iframeDoc.querySelectorAll(".o_snippets_preview_row > div")).toHaveLength(2);

    await contains(MOBILE_BTN).click();
    expect(iframeDoc.querySelectorAll(".o_snippets_preview_row > div")).toHaveLength(3);

    await contains(MOBILE_BTN).click();
    expect(iframeDoc.querySelectorAll(".o_snippets_preview_row > div")).toHaveLength(2);
});

test("a block can still be dropped while the mobile preview is on", async () => {
    const { getEditableContent } = await setupHTMLBuilderWithDummySnippet("<h1>Homepage</h1>");
    const editableContent = getEditableContent();
    await openSnippetDialog();

    await contains(MOBILE_BTN).click();
    expect(MOBILE_BTN).toHaveClass("text-success");

    await confirmAddSnippet("s_test");
    expect(".o_add_snippet_dialog").toHaveCount(0);
    expect(editableContent.querySelectorAll("[data-snippet='s_test']")).toHaveLength(1);
});
