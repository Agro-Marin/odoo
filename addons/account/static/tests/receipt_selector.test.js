import { describe, expect, test } from "@odoo/hoot";
import {
    defineModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

class Move extends models.Model {
    _name = "move";

    move_type = fields.Selection({
        selection: [
            ["in_invoice", "Vendor Bill"],
            ["in_receipt", "Purchase Receipt"],
            ["out_refund", "Credit Note"],
        ],
    });
    kind_id = fields.Many2one({ relation: "move.kind" });

    _records = [
        { id: 1, move_type: "out_refund", kind_id: 1 },
        { id: 2, move_type: "in_invoice", kind_id: 1 },
    ];
}

class MoveKind extends models.Model {
    _name = "move.kind";

    name = fields.Char();

    _records = [{ id: 1, name: "Rebate" }];
}

defineModels([Move, MoveKind]);

describe("ReceiptSelector label", () => {
    test("prints the unfiltered selection label", async () => {
        await mountView({
            type: "form",
            resModel: "move",
            resId: 1,
            arch: `<form><field name="move_type" widget="receipt_selector"/></form>`,
        });

        expect("[name='move_type']").toHaveText("Credit Note");
    });

    test("prints the label of a many2one", async () => {
        await mountView({
            type: "form",
            resModel: "move",
            resId: 1,
            arch: `<form><field name="kind_id" widget="receipt_selector" readonly="1"/></form>`,
        });

        expect("[name='kind_id']").toHaveText("Rebate");
    });
});
