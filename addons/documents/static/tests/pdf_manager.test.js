import { PdfManager } from "@documents/owl/components/pdf_manager/pdf_manager";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { press, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame, mockFetch } from "@odoo/hoot-mock";
import {
    contains,
    mountWithCleanup,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";

defineMailModels();

describe.current.tags("desktop");

let destroyedPdfs;
let revokedUrls;

beforeEach(() => {
    destroyedPdfs = [];
    revokedUrls = [];
    PdfManagerForTest.pdfError = null;
    PdfManagerForTest.numPages = 6;
    PdfManagerForTest.blankPages = [];
    patchWithCleanup(URL, {
        createObjectURL(file) {
            return `blob:mock/${file?.name || "anonymous"}`;
        },
        revokeObjectURL(url) {
            revokedUrls.push(url);
        },
    });
});

class PdfManagerForTest extends PdfManager {
    static pdfError = null;
    static numPages = 6;
    static blankPages = [];

    async _loadAssets() {}
    async _getPdf(url) {
        if (this.constructor.pdfError) {
            throw this.constructor.pdfError;
        }
        const pdf = {
            url,
            getPage: (number) => ({ number }),
            numPages: this.constructor.numPages,
            destroy: () => destroyedPdfs.push(pdf),
        };
        this._pdfDocuments.push(pdf);
        return pdf;
    }
    async _isBlankPage(page) {
        return this.constructor.blankPages.includes(page.number);
    }
    async _renderCanvas(page, { width, height }) {
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        return canvas;
    }
}

function mountPdfManager(props = {}) {
    return mountWithCleanup(PdfManagerForTest, {
        props: {
            documents: [
                {
                    id: 1,
                    name: "yop",
                    mimetype: "application/pdf",
                    available_embedded_actions_ids: [1, 2],
                    folder_id: { id: 1 },
                    tag_ids: { currentIds: [] },
                    owner_id: { id: 1 },
                    partner_id: { id: 1 },
                },
                {
                    id: 2,
                    name: "blip",
                    mimetype: "application/pdf",
                    available_embedded_actions_ids: [1],
                    folder_id: { id: 1 },
                    tag_ids: { currentIds: [] },
                    owner_id: { id: 1 },
                    partner_id: { id: 1 },
                },
            ],
            embeddedActions: [
                { id: 1, name: "action1" },
                { id: 2, name: "action2" },
            ],
            onProcessDocuments: async () => {},
            close: () => {},
            ...props,
        },
    });
}

/**
 * @param {PdfManager} manager
 * @returns {String[]}
 */
function listedPageIds(manager) {
    return manager.store.groupIds.flatMap((groupId) => [
        ...manager.store.groupData[groupId].pageIds,
    ]);
}

test(`Pdf Manager basic rendering`, async () => {
    await mountPdfManager();
    expect(".o_documents_pdf_manager_top_bar").toHaveCount(1, {
        message: "There should be one top bar",
    });
    expect(".o_documents_pdf_page_viewer").toHaveCount(1, {
        message: "There should be one page viewer",
    });
    expect(".o_pdf_manager_button:eq(0)").toHaveText("Split", {
        message: "There should be a split button",
    });
    expect(".o_pdf_manager_button:eq(2)").toHaveText("ADD FILE", {
        message: "There should be a ADD FILE button",
    });
    expect(".o_pdf_manager_button:eq(3)").toHaveText("ACTION1", {
        message: "There should be a ACTION1 button",
    });
    expect(".o_pdf_manager_button:eq(4)").toHaveText("ACTION2", {
        message: "There should be a ACTION2 button",
    });
    expect(".o_pdf_separator_selected").toHaveCount(1, {
        message: "There should be one active separator",
    });
    expect(".o_pdf_page").toHaveCount(12, { message: "There should be 12 pages" });
    expect(".o_documents_pdf_button_wrapper").toHaveCount(12, {
        message: "There should be 12 button wrappers",
    });
    expect(".o_pdf_group_name_wrapper").toHaveCount(2, {
        message: "There should be 2 name plates",
    });
});

test(`Pdf Manager: page interactions`, async () => {
    await mountPdfManager();

    expect(".o_pdf_separator_selected").toHaveCount(1, {
        message: "There should be one active separator",
    });

    await contains(".o_page_splitter_wrapper:eq(1)").click();
    expect(".o_pdf_separator_selected").toHaveCount(2, {
        message: "There should be 2 active separator",
    });
    expect(".o_pdf_page_selected").toHaveCount(12, {
        message: "There should be 12 selected pages",
    });

    await contains(".o_documents_pdf_page_selector:eq(3)").click();
    expect(".o_pdf_page_selected").toHaveCount(11, {
        mesage: "There should be 11 selected pages",
    });
});

test(`Pdf Manager: drag & drop`, async () => {
    await mountPdfManager();

    expect(".o_pdf_separator_selected").toHaveCount(1, {
        message: "There should be one active separator",
    });
    expect(".o_documents_pdf_page_frame:eq(6) .o_pdf_name_display").toHaveCount(1, {
        message: "The seventh page should have a name plate",
    });

    await contains(".o_documents_pdf_canvas_wrapper:eq(11)").dragAndDrop(
        ".o_documents_pdf_canvas_wrapper:eq(0)",
        null,
        {
            dataTransfer: new DataTransfer(),
        },
    );
    expect(".o_pdf_separator_selected").toHaveCount(1, {
        message: "There should be one active separator",
    });
    expect(".o_documents_pdf_page_frame:eq(6) .o_pdf_name_display").toHaveCount(0, {
        message: "The seventh page shouldn't have a name plate",
    });
    expect(".o_documents_pdf_page_frame:eq(7) .o_pdf_name_display").toHaveCount(1, {
        message: "The eight page should have a name plate",
    });
});

test(`Pdf Manager: select/Unselect all pages`, async () => {
    await mountPdfManager();

    await contains(".o_documents_pdf_page_viewer").click();
    expect(".o_pdf_page_selected").toHaveCount(0, {
        message: "There should be no page selected",
    });

    await press(["ctrl", "a"]);
    await animationFrame();
    expect(".o_pdf_page_selected").toHaveCount(12, {
        message: "There should be 12 pages selected",
    });

    await press(["ctrl", "a"]);
    await animationFrame();
    expect(".o_pdf_page_selected").toHaveCount(0, {
        message: "There should be no page selected",
    });
});

test(`Pdf Manager: select pages with mouse area selection`, async () => {
    await mountPdfManager();

    await press(["ctrl", "a"]);
    await animationFrame();
    expect(".o_pdf_page_selected").toHaveCount(0, {
        message: "There should be no page selected",
    });

    const viewer = queryOne(".o_documents_pdf_manager");
    const { top, left, width, height } = viewer.getBoundingClientRect();
    const { drop, moveTo } = await contains(".o_documents_pdf_manager").drag({
        position: { x: left, y: top },
    });
    const position = { x: left + width, y: top + height };
    await moveTo({ position });
    await drop({ position });
    expect(".o_pdf_page_selected").toHaveCount(12, {
        message: "There should be 12 pages selected",
    });
});

test("Pdf Manager: puts separators on active pages by pressing control+s", async () => {
    await mountPdfManager();

    await contains(".o_documents_pdf_page_viewer").click();
    expect(".o_pdf_page_selected").toHaveCount(0, {
        message: "There should be no page selected",
    });

    await press(["ctrl", "a"]);
    await animationFrame();
    expect(".o_pdf_page_selected").toHaveCount(12, {
        message: "There should be 12 pages selected",
    });

    await press(["ctrl", "s"]);
    await animationFrame();
    expect(".o_pdf_separator_selected").toHaveCount(11, {
        message: "There should be 11 active separators",
    });
});

test(`Pdf Manager: click on page bottom area selects the page`, async () => {
    await mountPdfManager();

    await contains(".o_documents_pdf_page_viewer").click();
    expect(".o_pdf_page_selected").toHaveCount(0, {
        message: "There should be no page selected",
    });

    await contains(".o_bottom_selection").click();
    expect(".o_pdf_page_selected").toHaveCount(1, {
        message: "There should be one page selected",
    });
});

test(`Pdf Manager: click on page selector selects the page`, async () => {
    await mountPdfManager();

    await contains(".o_documents_pdf_page_viewer").click();
    expect(".o_pdf_page_selected").toHaveCount(0, {
        message: "There should be no page selected",
    });

    await contains(".o_documents_pdf_page_selector").click();
    expect(".o_pdf_page_selected").toHaveCount(1, {
        message: "There should be one page selected",
    });
});

test(`Pdf Manager: arrow navigation`, async () => {
    await mountPdfManager();

    await contains(".o_documents_pdf_page_viewer").click();
    expect(".o_pdf_page_selected").toHaveCount(0, {
        message: "There should be no page selected",
    });

    await press("arrowRight");
    await animationFrame();
    expect(".o_documents_pdf_page_frame:eq(0) .o_pdf_page_focused").toHaveCount(1, {
        message: "The first page should be focused",
    });

    await press("arrowRight");
    await animationFrame();
    expect(".o_documents_pdf_page_frame:eq(1) .o_pdf_page_focused").toHaveCount(1, {
        message: "The first page should be focused",
    });
});

test(`Pdf Manager: arrow navigation + shift page activation`, async () => {
    await mountPdfManager();

    await contains(".o_documents_pdf_page_viewer").click();
    expect(".o_pdf_page_selected").toHaveCount(0, {
        message: "There should be no page selected",
    });

    await press(["shift", "arrowRight"]);
    await animationFrame();
    expect(".o_documents_pdf_page_frame:eq(0) .o_pdf_page_focused").toHaveCount(1, {
        message: "The first page should be focused",
    });

    await press(["shift", "arrowRight"]);
    await animationFrame();
    expect(".o_documents_pdf_page_frame:eq(1) .o_pdf_page_focused").toHaveCount(1, {
        message: "The second page should be focused",
    });

    await press(["shift", "arrowRight"]);
    await animationFrame();
    expect(".o_documents_pdf_page_frame:eq(2) .o_pdf_page_focused").toHaveCount(1, {
        message: "The third page should be focused",
    });
    expect(".o_pdf_page_selected").toHaveCount(3, {
        message: "3 pages should be selected",
    });

    await press(["shift", "arrowLeft"]);
    await press(["shift", "arrowLeft"]);
    await animationFrame();
    expect(".o_documents_pdf_page_frame:eq(0) .o_pdf_page_focused").toHaveCount(1, {
        message: "The first page should be focused",
    });
    expect(".o_pdf_page_selected").toHaveCount(1, {
        message: "One page should be selected",
    });
});

test(`Pdf Manager: ctrl+shift+arrow shortcut multiple activation`, async () => {
    await mountPdfManager();

    await contains(".o_documents_pdf_page_viewer").click();
    expect(".o_pdf_page_selected").toHaveCount(0, {
        message: "There should be no page selected",
    });

    await press("arrowRight");
    await press(["shift", "ctrl", "arrowRight"]);
    await animationFrame();
    expect(".o_pdf_page_selected").toHaveCount(6, {
        message: "There should be 6 pages selected",
    });
});

test(`Pdf Manager: ctrl+arrow shortcut navigation between groups`, async () => {
    await mountPdfManager();

    await contains(".o_documents_pdf_page_viewer").click();
    expect(".o_pdf_page_selected").toHaveCount(0, {
        message: "There should be no page selected",
    });

    await press("arrowRight");
    await press(["ctrl", "arrowRight"]);
    await animationFrame();
    expect(".o_documents_pdf_page_frame:eq(6) .o_pdf_page_focused").toHaveCount(1, {
        message: "The seventh page should be focused",
    });
});

test(`Pdf Manager: click on group name should select all the group`, async () => {
    await mountPdfManager();

    await contains(".o_documents_pdf_page_viewer").click();
    expect(".o_pdf_page_selected").toHaveCount(0, {
        message: "There should be no page selected",
    });

    await contains(".o_pdf_name_display").click();
    expect(".o_pdf_page_selected").toHaveCount(6, {
        message: "6 pages should be selected",
    });
});

test(`Pdf Manager: page preview behaviour`, async () => {
    await mountPdfManager();

    await contains(".o_documents_pdf_page_viewer").click();
    expect(".o_pdf_page_selected").toHaveCount(0, {
        message: "There should be no page selected",
    });

    await contains(".o_documents_pdf_canvas_wrapper").click();
    expect(".o_pdf_page_preview").toHaveCount(1, {
        message: "The previewer should be open",
    });
    expect(".o_page_index").toHaveText("1/12", {
        message: "Index of the first page should be displayed",
    });
    expect(".o_page_name").toHaveText("yop-p1", {
        message: "Name of the group should be displayed",
    });

    await press("arrowRight");
    await animationFrame();
    expect(".o_page_index").toHaveText("2/12", {
        message: "Index of the second page should be displayed",
    });
    expect(".o_page_name").toHaveText("yop-p2", {
        message: "Name of the group should be displayed",
    });
});

function mockPdfSplit({ status = 200, documentIds = [101] } = {}) {
    mockFetch((input) => {
        if (String(input).includes("/documents/pdf_split")) {
            expect.step(`pdf_split:${status}`);
            if (status !== 200) {
                return new Response(null, { status });
            }
            return new Response(JSON.stringify(documentIds), {
                status,
                headers: { "Content-Type": "application/json" },
            });
        }
    });
}

test(`Pdf Manager: a failed split does not duplicate the ignored pages`, async () => {
    const manager = await mountPdfManager();
    await contains(".o_pdf_name_display:eq(1)").click();
    expect(".o_pdf_page_selected").toHaveCount(6, {
        message: "only the first group should be selected",
    });

    mockPdfSplit({ status: 500 });
    await contains(".o_pdf_manager_button:eq(0)").click();
    await animationFrame();
    expect.verifySteps(["pdf_split:500"]);

    const pageIds = listedPageIds(manager);
    expect(pageIds).toHaveLength(12, { message: "the 12 pages are each listed once" });
    expect(new Set(pageIds).size).toBe(12, {
        message: "no page id appears in two groups",
    });
    expect(manager.store.numberOfPages).toBe(12, {
        message: "numberOfPages matches the real page count",
    });
    expect(".o_pdf_page").toHaveCount(12, {
        message: "no duplicated card is rendered",
    });

    mockPdfSplit({ status: 500 });
    await contains(".o_pdf_manager_button:eq(0)").click();
    await animationFrame();
    expect.verifySteps(["pdf_split:500"]);
    expect(listedPageIds(manager)).toHaveLength(12, {
        message: "retrying a failed split does not accumulate pages",
    });
    expect(manager.store.numberOfPages).toBe(12);
});

test(`Pdf Manager: deleting after a partial split does not crash`, async () => {
    const manager = await mountPdfManager();
    await press(["ctrl", "a"]);
    await animationFrame();
    for (const index of [0, 1, 2]) {
        await contains(`.o_documents_pdf_page_selector:eq(${index})`).click();
    }
    expect(".o_pdf_page_selected").toHaveCount(3);

    const committedPageId = listedPageIds(manager)[0];
    manager.store.focusedPage = committedPageId;

    mockPdfSplit();
    await contains(".o_pdf_manager_button:eq(0)").click();
    await animationFrame();
    expect.verifySteps(["pdf_split:200"]);

    expect(manager.store.pages[committedPageId]).toBeOfType("object", {
        message: "the committed page survives, its file is not fully consumed",
    });
    expect(manager.store.pages[committedPageId].groupId).toBe(false);
    expect(manager.store.focusedPage).toBe(undefined, {
        message: "the focus is released when the focused page is committed",
    });

    expect(() =>
        manager._removePage(committedPageId, { fromFile: true }),
    ).not.toThrow();
    expect(listedPageIds(manager)).toHaveLength(9, {
        message: "3 pages of yop + the 6 untouched pages of blip",
    });

    await press("delete");
    await animationFrame();
    expect(".o_dialog").toHaveCount(0, {
        message: "nothing is selected nor focused: no delete confirmation, no crash",
    });
});

test(`Pdf Manager: a PDF that fails to load releases the toolbar`, async () => {
    PdfManagerForTest.pdfError = Object.assign(new Error("404"), {
        name: "UnexpectedResponseException",
    });
    const manager = await mountPdfManager();
    await animationFrame();

    expect(manager.state.uploadingLock).toBe(false, {
        message: "the upload lock is released even though the PDF never loaded",
    });
    expect(".o_notification").toHaveCount(2, {
        message: "one notification per failed file",
    });
    expect(".o_notification_content:eq(0)").toHaveText("Could not open yop.");
    for (const button of queryAll(".o_pdf_manager_button")) {
        expect(button).toBeEnabled({
            message: `"${button.textContent.trim()}" stays usable after a load failure`,
        });
    }
    expect(() => manager._focusNextPage("right", false)).not.toThrow();
});

test(`Pdf Manager: an encrypted PDF gets a dedicated message`, async () => {
    PdfManagerForTest.pdfError = Object.assign(new Error("password"), {
        name: "PasswordException",
    });
    await mountPdfManager();
    await animationFrame();

    expect(".o_notification_content:eq(0)").toHaveText(
        "yop is password protected and cannot be split.",
    );
});

test(`Pdf Manager: forward drag inside a group lands on the target index`, async () => {
    const manager = await mountPdfManager();
    const [p1, p2, p3, p4, p5, p6] = listedPageIds(manager);

    await contains(".o_documents_pdf_canvas_wrapper:eq(0)").dragAndDrop(
        ".o_documents_pdf_canvas_wrapper:eq(3)",
        null,
        { dataTransfer: new DataTransfer() },
    );
    expect(listedPageIds(manager).slice(0, 6)).toEqual([p2, p3, p1, p4, p5, p6], {
        message: "the dragged page takes the target's place, it does not land after it",
    });

    await contains(".o_documents_pdf_canvas_wrapper:eq(2)").dragAndDrop(
        ".o_documents_pdf_canvas_wrapper:eq(0)",
        null,
        { dataTransfer: new DataTransfer() },
    );
    expect(listedPageIds(manager).slice(0, 6)).toEqual([p1, p2, p3, p4, p5, p6], {
        message: "dropping it back on the first page restores the original order",
    });
    expect(manager.store.numberOfPages).toBe(12, {
        message: "reordering never changes the page count",
    });
});

test(`Pdf Manager: pdf documents and object URLs are released`, async () => {
    const manager = await mountPdfManager();
    await manager._addFile("extra.pdf", { file: new File([""], "extra.pdf") });
    await animationFrame();
    expect(manager._pdfDocuments).toHaveLength(3);
    expect(manager._objectUrls).toEqual(["blob:mock/extra.pdf"]);

    const extraFileId = Object.keys(manager._newFiles).at(-1);
    for (const pageId of [...manager._newFiles[extraFileId].pageIds]) {
        manager._removePage(pageId, { fromFile: true });
    }
    expect(destroyedPdfs).toHaveLength(1, {
        message: "the consumed file's pdf.js document is destroyed right away",
    });
    expect(revokedUrls).toEqual(["blob:mock/extra.pdf"]);
    expect(manager._pdfDocuments).toHaveLength(2, {
        message: "the released document is dropped from the unmount cleanup list",
    });
    expect(manager._objectUrls).toEqual([]);

    manager.__owl__.app.destroy();
    expect(destroyedPdfs).toHaveLength(3, {
        message: "every remaining pdf.js document is destroyed on unmount",
    });
    expect(revokedUrls).toHaveLength(1, { message: "no double revoke" });
});

test(`Pdf Manager: splitting on blank pages asks before discarding groups`, async () => {
    PdfManagerForTest.blankPages = [3];
    const manager = await mountPdfManager();
    await animationFrame();
    expect(manager.store.groupIds).toHaveLength(2);

    await press(["shift", "s"]);
    await animationFrame();
    expect(".o_dialog").toHaveCount(1, {
        message: "a confirmation is required before wiping the existing grouping",
    });

    await contains(".o_dialog .btn-primary").click();
    await animationFrame();
    expect(manager.store.groupIds.length).toBeGreaterThan(2, {
        message: "confirming does split on the blank pages",
    });
    expect(listedPageIds(manager)).toHaveLength(12, {
        message: "blank-page splitting neither loses nor duplicates a page",
    });
    expect(manager.store.numberOfPages).toBe(12);
});

test(`Pdf Manager: numpad Enter commits a group rename`, async () => {
    const manager = await mountPdfManager();
    await contains(".o_pdf_name_display").click();
    await contains(".o_pdf_name_input").click();

    const input = queryOne(".o_pdf_name_input");
    input.value = "renamed";
    await press("Enter", { code: "NumpadEnter" });
    await animationFrame();

    expect(manager.store.groupData[manager.store.groupIds[0]].name).toBe("renamed", {
        message: "the numpad Enter key commits the rename like the main one",
    });
});
