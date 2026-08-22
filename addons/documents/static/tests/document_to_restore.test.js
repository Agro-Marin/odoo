import { DocumentsKanbanModel } from "@documents/views/kanban/documents_kanban_model";
import { describe, expect, test } from "@odoo/hoot";
import {
    defineModels,
    getService,
    mockService,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";

import { DocumentsModels, makeDocumentRecordData } from "./helpers/data.js";
import { makeDocumentsMockEnv } from "./helpers/model.js";
import { mountDocumentsKanbanView } from "./helpers/views/kanban.js";

describe.current.tags("desktop");

defineModels(DocumentsModels);

/**
 * @returns {Promise<Object>}
 */
async function mountRestoring(restoreId, count = 4) {
    const records = [];
    for (let i = 1; i <= count; i++) {
        records.push(makeDocumentRecordData(i, `Doc ${i}`));
    }
    DocumentsModels.DocumentsDocument._records = records;
    await makeDocumentsMockEnv();
    getService("document.document").documentIdToRestoreOnce = restoreId;
    let model;
    patchWithCleanup(DocumentsKanbanModel.prototype, {
        setup() {
            super.setup(...arguments);
            model = this;
        },
    });
    await mountDocumentsKanbanView();
    return model;
}

test("the requested document is hoisted to the top and starts selected", async () => {
    const model = await mountRestoring(3);

    expect(model.root.records[0].resId).toBe(3, {
        message: "the target is moved to the head of the first page",
    });
    expect(model.root.records[0].selected).toBe(true);
    expect(model.root.selection.map((r) => r.resId)).toEqual([3]);
});

test("the flag lives on the model, not on the shared service", async () => {
    const model = await mountRestoring(2);
    const documentService = getService("document.document");

    expect(documentService.documentIdToRestore).toBe(undefined, {
        message: "the service is not used as a side channel between the mixins",
    });
    expect(documentService.documentIdToRestoreOnce).toBe(undefined, {
        message: "the one-shot id is consumed by the load",
    });
    expect(model.documentIdToRestore).toBe(undefined, {
        message: "and the model releases it once the records have read it",
    });
});

test("nothing is selected when no document was requested", async () => {
    DocumentsModels.DocumentsDocument._records = [
        makeDocumentRecordData(1, "Doc 1"),
        makeDocumentRecordData(2, "Doc 2"),
    ];
    await makeDocumentsMockEnv();
    let model;
    patchWithCleanup(DocumentsKanbanModel.prototype, {
        setup() {
            super.setup(...arguments);
            model = this;
        },
    });
    await mountDocumentsKanbanView();

    expect(model.root.selection).toHaveLength(0);
    expect(model.root.records[0].resId).toBe(1, { message: "natural order is kept" });
});

test("an inaccessible document warns instead of selecting something else", async () => {
    const notifications = [];
    mockService("notification", {
        add: (message, options) => notifications.push({ message, options }),
    });
    const model = await mountRestoring(999);

    expect(model.root.selection).toHaveLength(0, {
        message: "no stand-in record is selected",
    });
    expect(notifications.map((n) => n.message)).toInclude(
        "Document not found or inaccessible.",
    );
});
