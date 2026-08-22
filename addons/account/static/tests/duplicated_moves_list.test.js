import { describe, expect, test } from "@odoo/hoot";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
    onRpc,
} from "@web/../tests/web_test_helpers";

import { defineAccountModels } from "./account_test_helpers.js";

describe.current.tags("desktop");

class AccountMove extends models.Model {
    _name = "account.move";

    ref = fields.Char();

    _records = [{ id: 1, ref: "b1" }];
}

// The surrounding models the list view reads (res.users for the cog menu), then
// ours on top of the shared `account.move` mock.
defineAccountModels();
defineModels([AccountMove]);

/**
 * `view_duplicated_moves_tree_js` used to carry a `js_class` whose controller
 * replaced `openRecord` with a bare `orm.call` + `doAction`. It now declares
 * `action` + `type` on the list, which the base controller dispatches through the
 * button protocol — the row's context, and a reload when the action closes.
 */
describe("duplicated moves list", () => {
    test("opening a row runs the model's business-doc button, then reloads", async () => {
        onRpc("account.move", "action_view_business_doc", ({ args }) => {
            expect.step(`action_view_business_doc:${args[0]}`);
            return false;
        });
        onRpc("account.move", "web_search_read", ({ parent }) => {
            expect.step("web_search_read");
            return parent();
        });

        await mountView({
            type: "list",
            resModel: "account.move",
            arch: `
                <list action="action_view_business_doc" type="object" create="false">
                    <field name="ref"/>
                </list>`,
        });
        await expect.waitForSteps(["web_search_read"]);

        await contains(".o_data_cell").click();

        await expect.waitForSteps([
            "action_view_business_doc:1",
            // The reload the old override dropped.
            "web_search_read",
        ]);
    });
});
