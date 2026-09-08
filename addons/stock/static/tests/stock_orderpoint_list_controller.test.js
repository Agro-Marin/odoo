import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { expect, test } from "@odoo/hoot";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
    onRpc,
} from "@web/../tests/web_test_helpers";

class StockLocation extends models.Model {
    _name = "stock.location";

    display_name = fields.Char();

    _records = [
        { id: 1, display_name: "Shelf A" },
        { id: 2, display_name: "Shelf B" },
    ];
}

class StockWarehouseOrderpoint extends models.Model {
    _name = "stock.warehouse.orderpoint";

    location_id = fields.Many2one({ relation: "stock.location" });
    product_min_qty = fields.Float();

    _records = [
        { id: 1, location_id: 1, product_min_qty: 1 },
        { id: 2, location_id: 2, product_min_qty: 2 },
    ];
}

defineModels([StockLocation, StockWarehouseOrderpoint]);
defineMailModels();

onRpc("stock.warehouse.orderpoint", "get_horizon_days", () => 0);

const arch = `
    <list js_class="stock_orderpoint_list" editable="bottom">
        <field name="location_id"/>
        <field name="product_min_qty"/>
    </list>
`;

const searchViewArch = `
    <search>
        <searchpanel>
            <field name="location_id"/>
        </searchpanel>
    </search>
`;

test("a new rule inherits the location the search panel is filtered on", async () => {
    await mountView({
        type: "list",
        resModel: "stock.warehouse.orderpoint",
        arch,
        searchViewArch,
    });

    await contains(".o_search_panel_category_value header:contains(Shelf B)").click();
    await contains(".o_control_panel_main_buttons .o_list_button_add").click();

    expect("[name=location_id] input").toHaveValue("Shelf B", {
        message:
            "creating a rule while the panel is narrowed to one location must" +
            " start it in that location, not empty",
    });
});

test("a new rule stays empty when no location is selected in the panel", async () => {
    await mountView({
        type: "list",
        resModel: "stock.warehouse.orderpoint",
        arch,
        searchViewArch,
    });

    await contains(".o_control_panel_main_buttons .o_list_button_add").click();

    expect("[name=location_id] input").toHaveValue("", {
        message: "with the panel on All, nothing must be put in the location",
    });
});
