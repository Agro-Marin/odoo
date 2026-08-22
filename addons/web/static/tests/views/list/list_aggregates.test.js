// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
    onRpc,
    webModels,
} from "@web/../tests/web_test_helpers";

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
    inverse_rate = fields.Float();

    _records = [
        { id: 1, name: "USD", symbol: "$", position: "before", inverse_rate: 1 },
        { id: 2, name: "EUR", symbol: "€", position: "after", inverse_rate: 0.5 },
    ];
}

defineModels([Partner, Currency, ResCompany, ResPartner, ResUsers]);

test.tags("desktop");
test("grouped monetary aggregate renders when the currency aggregate is absent", async () => {
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
        arch: `
            <list>
                <field name="name"/>
                <field name="amount"/>
            </list>`,
        groupBy: ["bar"],
    });

    expect(`.o_group_header`).toHaveCount(2);
    const lastNumber = queryOne(`.o_group_header:last .o_list_number`);
    expect(lastNumber.textContent.trim()).not.toBe("");
});

test.tags("desktop");
test("grouped footer converts single-currency groups to the company currency", async () => {
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

    await contains(`.o_data_row:eq(0) .o_list_record_selector input`).click();
    await contains(`.o_data_row:eq(2) .o_list_record_selector input`).click();

    const footerCell = queryOne(`tfoot td.o_list_number span`);
    expect(footerCell.textContent).toInclude("1,350.00");
    expect(`tfoot td.o_list_number sup`).toHaveCount(1);
});

test.tags("desktop");
test("no total when one currency has no exchange rate", async () => {
    onRpc("res.currency", "read", ({ parent }) =>
        parent().filter((/** @type {any} */ r) => r.id !== 2),
    );

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
    expect(footerCell.textContent.trim()).toBe("?");
    expect(footerCell.textContent).not.toInclude("2,000");
});

test.tags("desktop");
test("a known rate still converts once every currency is covered", async () => {
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

    expect(queryOne(`tfoot td.o_list_number span`).textContent).toInclude("1,850.00");
});

test.tags("desktop");
test("a failing res.currency.read degrades the total, not the view", async () => {
    onRpc("res.currency", "read", () => {
        throw new Error("rate service down");
    });

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

    expect(`.o_data_row`).toHaveCount(3);
    expect(queryOne(`tfoot td.o_list_number span`).textContent.trim()).toBe("?");
});

test.tags("desktop");
test("rates are not fetched when no monetary column carries an aggregate", async () => {
    let rateReads = 0;
    onRpc("res.currency", "read", ({ parent }) => {
        rateReads++;
        return parent();
    });

    await mountView({
        resModel: "partner",
        type: "list",
        arch: `
            <list>
                <field name="name"/>
                <field name="amount"/>
                <field name="currency_id"/>
            </list>`,
    });

    expect(rateReads).toBe(0);
});

test.tags("desktop");
test("a malformed digits= names the attribute instead of dying anonymously", async () => {
    expect.errors(1);
    let caught = null;
    try {
        await mountView({
            resModel: "partner",
            type: "list",
            arch: `<list>
                    <field name="name"/>
                    <field name="amount" sum="Total" digits="[16,notjson]"/>
                </list>`,
        });
    } catch (error) {
        caught = error;
    }
    await animationFrame();
    expect.verifyErrors([/owl lifecycle/]);
    expect(String(caught?.cause?.message)).toMatch(
        /invalid "digits" attribute on <field name="amount"\/>/,
    );
});

test.tags("desktop");
test("a well-formed digits= reaches the formatter", async () => {
    await mountView({
        resModel: "partner",
        type: "list",
        arch: `<list>
                <field name="name"/>
                <field name="amount" sum="Total" digits="[16,3]"/>
            </list>`,
    });
    expect(queryOne(`tfoot td.o_list_number span`).textContent).toInclude(".000");
});
