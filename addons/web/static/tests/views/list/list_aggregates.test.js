// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import {
    contains,
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
    date = fields.Date();
    // company-currency amount per foreign unit (see services/currency.js)
    inverse_rate = fields.Float();

    _records = [
        { id: 1, name: "USD", symbol: "$", position: "before", inverse_rate: 1 },
        { id: 2, name: "EUR", symbol: "€", position: "after", inverse_rate: 0.5 },
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

test.tags("desktop");
test("grouped footer converts single-currency groups to the company currency", async () => {
    // Groups: bar=true is all-USD (1200 + 500), bar=false is all-EUR (300).
    // EUR inverse_rate is 0.5 → the footer total is 1700 + 300 × 0.5 = 1850,
    // flagged with the multi-currency indicator.
    await mountView({
        resModel: "partner",
        type: "list",
        arch: `
            <list>
                <field name="name"/>
                <field name="amount" sum="Total"/>
                <field name="currency_id"/>
            </list>`,
        groupBy: ["bar"],
    });

    const footerCell = queryOne(`tfoot td.o_list_number span`);
    expect(footerCell.textContent).toInclude("1,850.00");
    expect(`tfoot td.o_list_number sup`).toHaveCount(1);
});

test.tags("desktop");
test("grouped footer renders no total when a group mixes currencies", async () => {
    // bar=true group holds USD and EUR records: its server-side sum already
    // mixes currencies and cannot be converted client-side, so the footer
    // must render the multi-currency indicator WITHOUT a total (previously
    // the raw mixed sum was presented as company currency and added to the
    // converted sums of the other groups).
    Partner._records[1].currency_id = 2;

    await mountView({
        resModel: "partner",
        type: "list",
        arch: `
            <list>
                <field name="name"/>
                <field name="amount" sum="Total"/>
                <field name="currency_id"/>
            </list>`,
        groupBy: ["bar"],
    });

    const footerCell = queryOne(`tfoot td.o_list_number span`);
    expect(footerCell.textContent.trim()).toBe("?");
    expect(`tfoot td.o_list_number sup`).toHaveCount(1);

    // The indicator has no total to convert: hovering must not open the
    // multi-currency popover (the explanatory tooltip may still show).
    await contains(`tfoot td.o_list_number sup`).hover();
    expect(`.o_multi_currency_popover`).toHaveCount(0);
});

test.tags("desktop");
test("selection footer converts mixed-currency records to the company currency", async () => {
    await mountView({
        resModel: "partner",
        type: "list",
        arch: `
            <list>
                <field name="name"/>
                <field name="amount" sum="Total"/>
                <field name="currency_id"/>
            </list>`,
    });

    // Select an USD record (1200) and an EUR record (300 × 0.5 = 150).
    await contains(`.o_data_row:eq(0) .o_list_record_selector input`).click();
    await contains(`.o_data_row:eq(2) .o_list_record_selector input`).click();

    const footerCell = queryOne(`tfoot td.o_list_number span`);
    expect(footerCell.textContent).toInclude("1,350.00");
    expect(`tfoot td.o_list_number sup`).toHaveCount(1);
});

test.tags("desktop");
test("non-grouped footer stays single-currency when some rows have an empty currency", async () => {
    // All valued rows are USD; one (blank/zero) row carries no currency. The
    // empty currency must not be counted as a distinct currency, so the footer
    // renders a plain USD total WITHOUT the multi-currency indicator (before the
    // fix, the empty currency became a `false` sentinel that inflated the set to
    // size 2 and spuriously flagged the total as multi-currency).
    Partner._records = [
        { id: 1, name: "a", bar: true, amount: 1200, currency_id: 1 },
        { id: 2, name: "b", bar: true, amount: 500, currency_id: 1 },
        { id: 3, name: "c", bar: false, amount: 0, currency_id: false },
    ];

    await mountView({
        resModel: "partner",
        type: "list",
        arch: `
            <list>
                <field name="name"/>
                <field name="amount" sum="Total"/>
                <field name="currency_id"/>
            </list>`,
    });

    const footerCell = queryOne(`tfoot td.o_list_number span`);
    expect(footerCell.textContent).toInclude("1,700.00");
    expect(`tfoot td.o_list_number sup`).toHaveCount(0);
});
