import { expect, test } from "@odoo/hoot";
import { waitFor, waitForNone } from "@odoo/hoot-dom";
import { contains, mockService } from "@web/../tests/web_test_helpers";
import { defineDocumentsModels } from "@documents/../tests/documents_test_helpers";
import { start } from "@mail/../tests/mail_test_helpers";

defineDocumentsModels();

test("activity menu widget: documents request button", async () => {
    mockService("action", {
        doAction(action) {
            // The web client with no action in the URL opens the home menu
            // through this same service; only the button's dispatch is asserted.
            if (action !== "menu") {
                expect.step(action);
            }
        },
    });
    await start();
    await contains(".o_menu_systray i[aria-label='Activities']").click();
    await waitFor(".o-mail-ActivityMenu");
    await contains(".o_sys_documents_request").click();
    await waitForNone(".o-mail-ActivityMenu");
    expect.verifySteps(["documents.action_request_form"]);
});
