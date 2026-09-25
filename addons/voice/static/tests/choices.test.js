// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { INVOICE_LIST, ORDER_FORM, vocabulary } from "@voice/../tests/fixtures";
import { choicesOf, proposalsFromChoices } from "@voice/interpreter/choices";
import { RISK } from "@voice/interpreter/interpreter";

describe.current.tags("headless");

test("the choices are what the screen offers, and nothing else", () => {
    const ids = choicesOf(vocabulary(INVOICE_LIST)).map((choice) => choice.id);
    expect(ids).toInclude("filter:unpaid");
    expect(ids).toInclude("period:invoice_date:month-1");
    expect(ids).toInclude("groupby:invoice_user_id");
    expect(ids).toInclude("search:partner_id");
    expect(ids).toInclude("view:kanban");
    expect(ids).not.toInclude("view:list");
    expect(ids).toInclude("menu:0");
    expect(ids.some((id) => id.startsWith("button:"))).toBe(false);
    const formIds = choicesOf(vocabulary(ORDER_FORM)).map((choice) => choice.id);
    expect(formIds).toInclude("set:quantity");
    expect(formIds).toInclude("button:0");
});

test("search picks become one search proposal, as the grammar makes it", () => {
    const [search] = proposalsFromChoices(
        [
            { id: "filter:unpaid" },
            { id: "period:invoice_date:month-1" },
            { id: "groupby:invoice_user_id" },
            { id: "search:partner_id", value: " Acme " },
            { id: "filter:not_offered" },
        ],
        vocabulary(INVOICE_LIST),
    );
    expect(search).toMatchObject({
        kind: "search",
        risk: RISK.SEARCH,
        spec: {
            filters: ["unpaid"],
            dateFilters: [{ name: "invoice_date", generatorIds: ["month-1"] }],
            groupBys: ["invoice_user_id"],
            fieldSearches: [{ fieldName: "partner_id", value: "Acme" }],
        },
    });
});

test("a menu is taken alone, values are parsed, and one button at most", () => {
    const opened = proposalsFromChoices(
        [{ id: "filter:unpaid" }, { id: "menu:0" }],
        vocabulary(INVOICE_LIST),
    );
    expect(opened.map((p) => p.kind)).toEqual(["open_menu"]);
    const form = proposalsFromChoices(
        [
            { id: "set:quantity", value: "cinco" },
            { id: "set:priority", value: "altísima" },
            { id: "button:0" },
            { id: "button:1" },
        ],
        vocabulary(ORDER_FORM),
    );
    expect(form.map((p) => [p.kind, p.value ?? p.button?.label])).toEqual([
        ["set_field", 5],
        ["click_button", "Confirmar"],
    ]);
});
