// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import {
    defineModels,
    fields,
    models,
    mountView,
    onRpc,
    webModels,
} from "@web/../tests/web_test_helpers";

// These tests live in a dedicated file (mirroring `list_aggregates.js`) so
// they don't collide with the concurrently-edited `list_view.test.js`.

const { ResCompany, ResPartner, ResUsers } = webModels;

class Partner extends models.Model {
    _name = "partner";

    name = fields.Char();
    bar = fields.Boolean();
    amount = fields.Monetary({ currency_field: "currency_id" });
    currency_id = fields.Many2one({ relation: "res.currency", default: 1 });

    _records = [
        { id: 1, name: "a", bar: true, amount: 1200, currency_id: 1 },
        { id: 2, name: "b", bar: true, amount: 500, currency_id: 1 },
        { id: 3, name: "c", bar: false, amount: 300, currency_id: 2 },
    ];
}

class Currency extends models.Model {
    _name = "res.currency";

    name = fields.Char();
    symbol = fields.Char();
    position = fields.Selection({
        selection: [
            ["after", "A"],
            ["before", "B"],
        ],
    });

    _records = [
        { id: 1, name: "USD", symbol: "$", position: "before" },
        { id: 2, name: "EUR", symbol: "€", position: "after" },
    ];
}

defineModels([Partner, Currency, ResCompany, ResPartner, ResUsers]);

test.tags("desktop");
test("grouped monetary aggregate renders when the currency aggregate is absent", async () => {
    // Simulate a server (e.g. a custom read_group) that did not send the
    // currency aggregate alongside the monetary sum. `formatGroupAggregate`
    // must guard the missing aggregate instead of dereferencing `.length`.
    onRpc("web_read_group", ({ parent }) => {
        const result = parent();
        for (const group of result.groups) {
            delete group["currency_id:array_agg_distinct"];
            delete group["amount:sum_currency"];
        }
        return result;
    });

    await mountView({
        resModel: "partner",
        type: "list",
        // No `sum=` on amount: the monetary aggregate still renders in the
        // group header (the model aggregates monetary fields by default),
        // while the footer path is not exercised here.
        arch: `
            <list>
                <field name="name"/>
                <field name="amount"/>
            </list>`,
        groupBy: ["bar"],
    });

    // Before the fix, rendering the group headers threw
    // (Cannot read properties of undefined (reading 'length')).
    expect(`.o_group_header`).toHaveCount(2);
    const lastNumber = queryOne(`.o_group_header:last .o_list_number`);
    expect(lastNumber.textContent.trim()).not.toBe("");
});
