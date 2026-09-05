import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { expect, test } from "@odoo/hoot";
import {
    defineActions,
    getService,
    mountWithCleanup,
    onRpc,
} from "@web/../tests/web_test_helpers";
import { WebClient } from "@web/webclient/webclient";

defineActions([
    {
        id: 42,
        name: "Stock report",
        tag: "stock_report_generic",
        type: "ir.actions.client",
        context: {},
        params: {},
    },
]);
defineMailModels();

function line(overrides = {}) {
    return {
        id: 1,
        model: "stock.move.line",
        model_id: 7,
        parent_id: false,
        usage: "internal",
        is_used: false,
        lot_name: "LOT-EXP-TRC",
        lot_id: 3,
        reference: "WH/IN/00001",
        location_source: "Partners/Vendors",
        location_destination: "WH/Stock",
        partner_id: false,
        picking_type_code: "incoming",
        res_id: 11,
        res_model: "stock.picking",
        expiration_date: "2026-12-31 10:00:00",
        columns: [
            "WH/IN/00001",
            "Traced Yoghurt",
            "01/01/2026 00:00:00",
            "LOT-EXP-TRC",
            "12/31/2026",
            "Partners/Vendors",
            "WH/Stock",
            "5.00 Units",
        ],
        level: 1,
        unfoldable: false,
        ...overrides,
    };
}

test("the expiration date is headed right after the lot", async function () {
    onRpc("get_main_lines", () => [line()]);
    await mountWithCleanup(WebClient);
    await getService("action").doAction(42);

    const headers = [...document.querySelectorAll(".o_report_header th")].map((th) =>
        th.textContent.trim()
    );
    expect(headers).toEqual([
        "Reference",
        "Product",
        "Date",
        "Lot/Serial #",
        "Expiration Date",
        "From",
        "To",
        "Quantity",
    ]);
});

test("every row is as wide as the header", async function () {
    onRpc("get_main_lines", () => [line()]);
    await mountWithCleanup(WebClient);
    await getService("action").doAction(42);

    const width = document.querySelectorAll(".o_report_header th").length;
    for (const row of document.querySelectorAll("tbody tr")) {
        expect(row.querySelectorAll("td")).toHaveLength(width);
    }
    expect("tbody tr td:nth-child(5)").toHaveText("12/31/2026");
});
