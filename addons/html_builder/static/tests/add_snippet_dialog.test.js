import {
    confirmAddSnippet,
    setupHTMLBuilderWithDummySnippet,
    waitForSnippetDialog,
} from "@html_builder/../tests/helpers";
import { describe, expect, test } from "@odoo/hoot";
import { animationFrame, queryOne } from "@odoo/hoot-dom";
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

/**
 * A keydown raised inside the preview iframe. The point of the test is that the
 * top window never sees it, so it cannot be sent with the usual helpers.
 */
async function pressInPreview(hotkey) {
    const iframeDoc = queryOne(SNIPPET_IFRAME).contentDocument;
    iframeDoc.body.focus();
    iframeDoc.body.dispatchEvent(
        new iframeDoc.defaultView.KeyboardEvent("keydown", {
            key: hotkey.key,
            altKey: Boolean(hotkey.altKey),
            bubbles: true,
        })
    );
    await animationFrame();
}

test("Escape closes the dialog from inside the preview", async () => {
    await setupHTMLBuilderWithDummySnippet("<h1>Homepage</h1>");
    await openSnippetDialog();
    expect(".o_add_snippet_dialog").toHaveCount(1);

    await pressInPreview({ key: "Escape" });
    expect(".o_add_snippet_dialog").toHaveCount(0);
});

test("the search box has a hotkey of its own", async () => {
    await setupHTMLBuilderWithDummySnippet("<h1>Homepage</h1>");
    await openSnippetDialog();
    expect(".o_add_snippet_dialog_search").toHaveAttribute("data-hotkey", "S");

    await pressInPreview({ key: "s", altKey: true });
    await animationFrame();
    expect(".o_add_snippet_dialog_search").toBeFocused();
});
