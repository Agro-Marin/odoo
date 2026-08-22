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

defineAccountModels();
defineModels([AccountMove]);

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
            "web_search_read",
        ]);
    });
});
