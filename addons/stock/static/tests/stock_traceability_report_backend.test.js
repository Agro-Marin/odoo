import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { expect, test } from "@odoo/hoot";
import { click } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
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

test("Rendering with no lines", async function () {
    onRpc("get_main_lines", () => []);
    await mountWithCleanup(WebClient);

    await getService("action").doAction(42);
    expect(".o_stock_reports_page").toHaveText("No operation made on this lot.");
});

/**
 * A traceability line as `get_main_lines` / `get_lines` return them: the report
 * builds its own payload, so the fields the template reads are all there is.
 */
function reportLine(id, { unfoldable }) {
    return {
        id,
        model_id: id,
        model: "stock.move.line",
        res_id: id,
        res_model: "stock.move.line",
        reference: `REF/${id}`,
        lot_name: false,
        location_source: "Vendors",
        location_destination: "WH/Stock",
        picking_type_code: "incoming",
        is_used: false,
        unfoldable,
        level: 0,
        columns: [`REF/${id}`, "Product", "", "", "", "", "1.00 Units"],
    };
}

test("Unfold opens every level and Fold closes them again", async function () {
    // Two roots, each with a child that itself has a grandchild, so the
    // recursion has something to recurse into.
    onRpc("get_main_lines", () => [
        reportLine(1, { unfoldable: true }),
        reportLine(2, { unfoldable: true }),
    ]);
    onRpc("get_lines", ({ args }) => {
        const parentId = args[0];
        return [reportLine(parentId * 10 + 1, { unfoldable: parentId < 10 })];
    });
    await mountWithCleanup(WebClient);
    await getService("action").doAction(42);

    expect("tbody tr").toHaveCount(2);

    await click("button:contains(Unfold)");
    await animationFrame();
    expect("tbody tr").toHaveCount(6);

    await click("button:contains(Fold)");
    await animationFrame();
    expect("tbody tr").toHaveCount(2);
});

test("The fold control stays hidden when nothing can be unfolded", async function () {
    onRpc("get_main_lines", () => [reportLine(1, { unfoldable: false })]);
    await mountWithCleanup(WebClient);
    await getService("action").doAction(42);

    expect("tbody tr").toHaveCount(1);
    expect("button:contains(Unfold)").toHaveCount(0);
    expect("button:contains(Fold)").toHaveCount(0);
});
