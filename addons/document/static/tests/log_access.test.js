import { describe, expect, test } from "@odoo/hoot";
import { runAllTimers } from "@odoo/hoot-mock";
import {
    contains,
    defineModels,
    makeServerError,
    onRpc,
} from "@web/../tests/web_test_helpers";

import { DocumentsModels, makeDocumentRecordData } from "./helpers/data.js";
import { makeDocumentsMockEnv } from "./helpers/model.js";
import { mountDocumentsKanbanView } from "./helpers/views/kanban.js";

describe.current.tags("desktop");

defineModels(DocumentsModels);

async function mountAndFocusDocument() {
    DocumentsModels.DocumentsDocument._records = [
        makeDocumentRecordData(1, "Folder 1", {
            type: "folder",
            user_permission: "edit",
        }),
        makeDocumentRecordData(2, "Doc 2"),
    ];
    await makeDocumentsMockEnv();
    await mountDocumentsKanbanView();
    await contains(".o_kanban_record:contains('Doc 2') .o_record_selector").click();
    await runAllTimers();
}

test("a failing touch RPC does not surface to the user", async () => {
    onRpc("/documents/touch/accessTokenDoc2", () => {
        expect.step("touch attempted");
        throw makeServerError({ message: "access log unavailable" });
    });

    await mountAndFocusDocument();

    expect.verifySteps(["touch attempted"]);
    expect(".o_kanban_renderer").toHaveCount(1);
});

test("a successful touch still reaches the caller that inspects the result", async () => {
    onRpc("/documents/touch/accessTokenDoc2", () => {
        expect.step("touch ok");
        return { reload: false };
    });

    await mountAndFocusDocument();

    expect.verifySteps(["touch ok"]);
});
