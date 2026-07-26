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

/**
 * `/documents/touch/<token>` access tracking.
 *
 * `DocumentService.logAccess` is a debounced fire-and-forget side effect of
 * navigating: focusing a record (every selection, every arrow key) and selecting
 * a folder both call it, and two of the three call sites ignore the result
 * entirely.
 *
 * This fork's `debounce` settles every queued awaiter with the trailing
 * execution's outcome -- rejections included -- so a failing touch RPC came out
 * of a floating promise as an unhandled rejection, which the webclient turns
 * into the global error dialog. Losing an access timestamp must not interrupt
 * the user.
 */
describe.current.tags("desktop");

defineModels(DocumentsModels);

/** Mount a kanban and focus a document, which is what triggers the touch. */
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
    // logAccess is debounced by 1s; let the trailing execution run.
    await runAllTimers();
}

test("a failing touch RPC does not surface to the user", async () => {
    onRpc("/documents/touch/accessTokenDoc2", () => {
        expect.step("touch attempted");
        throw makeServerError({ message: "access log unavailable" });
    });

    await mountAndFocusDocument();

    expect.verifySteps(["touch attempted"]);
    // The assertion is that the run produced no unhandled error for HOOT to
    // report, and that the view survived.
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
