import { describe, expect, test } from "@odoo/hoot";
import { press, waitFor, waitForNone } from "@odoo/hoot-dom";
import {
    contains,
    defineActions,
    defineModels,
    getService,
    mountWithCleanup,
} from "@web/../tests/web_test_helpers";
import { WebClient } from "@web/webclient/webclient";

import { DocumentsModels, getDocumentsTestServerModelsData } from "./helpers/data.js";
import { makeDocumentsMockEnv } from "./helpers/model.js";
import { basicDocumentsKanbanArch } from "./helpers/views/kanban.js";
import { getEnrichedSearchArch } from "./helpers/views/search.js";

describe.current.tags("desktop");

defineModels(DocumentsModels);

defineActions([
    {
        id: 1,
        name: "Documents",
        res_model: "documents.document",
        views: [[false, "kanban"]],
    },
]);

async function mountWithPreviewableDocument() {
    const serverData = getDocumentsTestServerModelsData([
        {
            attachment_id: 1,
            id: 2,
            name: "text_file.txt",
            user_permission: "edit",
            mimetype: "image/webp",
        },
    ]);
    serverData["ir.attachment"] = [
        { id: 1, name: "text_file.txt", mimetype: "image/webp" },
    ];
    DocumentsModels.DocumentsDocument._views = {
        kanban: basicDocumentsKanbanArch,
        [["search", false]]: getEnrichedSearchArch(),
    };
    await makeDocumentsMockEnv({ serverData });
    await mountWithCleanup(WebClient);
    await getService("action").doAction(1);
    return getService("document.document");
}

test("the preview releases documentList when it closes", async () => {
    const documentService = await mountWithPreviewableDocument();

    expect(documentService.documentList).toBe(undefined, {
        message: "nothing is published before a preview is opened",
    });

    await contains(
        ".o_kanban_record:contains('text_file.txt') [name='document_preview']",
    ).click();
    await waitFor(".o-FileViewer");
    expect(documentService.documentList).not.toBe(null);
    expect(documentService.documentList.documents.length).toBeGreaterThan(0);

    await press("escape");
    await waitForNone(".o-FileViewer");

    expect(documentService.documentList).toBe(null, {
        message:
            "closing the preview releases the controller closures and the previewed records",
    });
});

test("closing twice is a no-op", async () => {
    const documentService = await mountWithPreviewableDocument();

    await contains(
        ".o_kanban_record:contains('text_file.txt') [name='document_preview']",
    ).click();
    await waitFor(".o-FileViewer");
    await press("escape");
    await waitForNone(".o-FileViewer");

    await getService("action").currentController.props.resModel;
    expect(documentService.documentList).toBe(null);
    expect(() => documentService.bus.trigger("DOCUMENT_RELOAD")).not.toThrow();
});
