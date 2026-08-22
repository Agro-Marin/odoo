import { describe, expect, test } from "@odoo/hoot";
import { queryAllTexts } from "@odoo/hoot-dom";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

class Account extends models.Model {
    _name = "account";

    account_type = fields.Selection({
        selection: [
            ["asset_cash", "Bank and Cash"],
            ["liability_payable", "Payable"],
            ["equity", "Equity"],
            ["income", "Income"],
            ["expense", "Expenses"],
            ["off_balance", "Off-Balance Sheet"],
            // No prefix claims this one. A localisation adding an account type
            // must not have it silently vanish from the selector.
            ["memorandum", "Memorandum"],
        ],
    });

    _records = [{ id: 1, account_type: "asset_cash" }];
}

defineModels([Account]);

describe("AccountTypeSelection groups", () => {
    test("offers every account type, prefixed or not", async () => {
        await mountView({
            type: "form",
            resModel: "account",
            resId: 1,
            arch: `<form><field name="account_type" widget="account_type_selection"/></form>`,
        });

        await contains(
            ".o_field_widget[name='account_type'] .o_select_menu_toggler",
        ).click();

        expect(queryAllTexts(".o_select_menu_item")).toEqual([
            "Bank and Cash",
            "Payable",
            "Equity",
            "Income",
            "Expenses",
            "Off-Balance Sheet",
            "Memorandum",
        ]);
    });
});
