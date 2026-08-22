import { documentsClientThumbnailService } from "@documents/views/helper/documents_client_thumbnail_service";
import { describe, expect, test } from "@odoo/hoot";
import {
    defineModels,
    getService,
    makeServerError,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { Deferred } from "@web/core/utils/concurrency";

import {
    DocumentsModels,
    getDocumentsTestServerModelsData,
    makeDocumentRecordData,
    mimetypeExamplesBase64,
} from "./helpers/data.js";
import { makeDocumentsMockEnv } from "./helpers/model.js";
import { mountDocumentsKanbanView } from "./helpers/views/kanban.js";

describe.current.tags("desktop");

defineModels(DocumentsModels);

function drainThumbnailQueue() {
    return getService("documents_client_thumbnail").enqueueRecords([]);
}

async function mountWithPendingThumbnail() {
    const serverData = getDocumentsTestServerModelsData([
        makeDocumentRecordData(3, "Test Document", {
            thumbnail_status: "client_generated",
            attachment_id: 2,
            folder_id: 1,
            mimetype: "image/webp",
        }),
    ]);
    serverData["ir.attachment"] = [{ id: 2, name: "binary" }];
    await makeDocumentsMockEnv({ serverData });
    patchWithCleanup(documentsClientThumbnailService, {
        _getLoadedImage() {
            const img = new Image();
            const imagePromise = new Deferred();
            img.onload = () => imagePromise.resolve(img);
            img.src = "data:image/webp;base64," + mimetypeExamplesBase64.WEBP;
            return imagePromise;
        },
    });
    await mountDocumentsKanbanView();
}

test("a failing update_thumbnail RPC does not surface to the user", async () => {
    onRpc("/documents/document/3/update_thumbnail", () => {
        expect.step("update_thumbnail attempted");
        throw makeServerError({ message: "thumbnail storage is unavailable" });
    });

    await mountWithPendingThumbnail();
    await drainThumbnailQueue();

    expect.verifySteps(["update_thumbnail attempted"]);
    expect(".o_kanban_record:contains('Test Document')").toHaveCount(1, {
        message: "the view is still usable after the thumbnail failed",
    });
});

test("a thumbnail failure does not stop the queue for later records", async () => {
    const serverData = getDocumentsTestServerModelsData([
        makeDocumentRecordData(3, "Doc A", {
            thumbnail_status: "client_generated",
            attachment_id: 2,
            folder_id: 1,
            mimetype: "image/webp",
        }),
        makeDocumentRecordData(4, "Doc B", {
            thumbnail_status: "client_generated",
            attachment_id: 3,
            folder_id: 1,
            mimetype: "image/webp",
        }),
    ]);
    serverData["ir.attachment"] = [
        { id: 2, name: "a" },
        { id: 3, name: "b" },
    ];
    onRpc("/documents/document/3/update_thumbnail", () => {
        expect.step("A failed");
        throw makeServerError({ message: "nope" });
    });
    onRpc("/documents/document/4/update_thumbnail", () => {
        expect.step("B stored");
        return true;
    });

    await makeDocumentsMockEnv({ serverData });
    patchWithCleanup(documentsClientThumbnailService, {
        _getLoadedImage() {
            const img = new Image();
            const imagePromise = new Deferred();
            img.onload = () => imagePromise.resolve(img);
            img.src = "data:image/webp;base64," + mimetypeExamplesBase64.WEBP;
            return imagePromise;
        },
    });
    await mountDocumentsKanbanView();
    await drainThumbnailQueue();

    expect.verifySteps(["A failed", "B stored"]);
});

test("a PDF the route refuses is marked failed, not retried forever", async () => {
    const serverData = getDocumentsTestServerModelsData([
        makeDocumentRecordData(3, "Broken PDF", {
            thumbnail_status: "client_generated",
            attachment_id: 2,
            folder_id: 1,
            mimetype: "application/pdf",
        }),
    ]);
    serverData["ir.attachment"] = [{ id: 2, name: "broken" }];
    let stored;
    onRpc("/documents/document/3/update_thumbnail", async (request) => {
        stored = (await request.json()).params.thumbnail;
        expect.step("update_thumbnail");
        return true;
    });
    await makeDocumentsMockEnv({ serverData });
    patchWithCleanup(documentsClientThumbnailService, {
        _getPdfThumbnail() {
            return { thumbnail: undefined, isPdfValid: false, pdfEnabled: true };
        },
    });
    await mountDocumentsKanbanView();
    await drainThumbnailQueue();

    expect.verifySteps(["update_thumbnail"]);
    expect(stored).toBe(false, { message: "stored as a definitive failure" });
});
