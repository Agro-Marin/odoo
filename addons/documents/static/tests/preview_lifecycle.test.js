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

/**
 * Lifetime of `documentService.documentList`.
 *
 * That object is built by `useDocumentsViewFilePreviewer` and closes over the
 * controller that opened the preview: `setPreviewStore`,
 * `getSelectedDocumentsElements` and the component's `root` ref, plus every
 * previewed record. The service is a singleton and never released it, so a
 * closed preview left a whole dead controller and its record set reachable, and
 * the next view's "documents-close-preview" ran the *previous* controller's
 * callback.
 */
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

/**
 * Mount a documents kanban holding one previewable image document.
 */
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

    // Every close path goes through `documentList?.onDeleteCallback()`, and a
    // documents model reload fires "documents-close-preview" on each load -- so
    // the second call has to land on an already-released list without throwing.
    await getService("action").currentController.props.resModel;
    expect(documentService.documentList).toBe(null);
    expect(() => documentService.bus.trigger("DOCUMENT_RELOAD")).not.toThrow();
});
