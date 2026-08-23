import { expect, test } from "@odoo/hoot";
import { click } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import {
    defineModels,
    defineWebModels,
    fields,
    mockService,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";

class HistoryLine extends models.Model {
    _name = "history.line";
    price_unit = fields.Float();
    product_id = fields.Many2one({ relation: "product" });
    partner_id = fields.Many2one({ relation: "res.partner" });
    _records = [
        { id: 1, price_unit: 10, product_id: 1, partner_id: 1 },
        { id: 2, price_unit: 20, product_id: false, partner_id: 1 },
    ];
}

class Product extends models.Model {
    _name = "product";
    name = fields.Char();
    _records = [{ id: 1, name: "Widget" }];
}

defineWebModels();
defineModels([HistoryLine, Product]);

const ARCH = `<list>
        <field name="price_unit"/>
        <widget name="price_history" options="{'action': 'some_module.some_action'}"/>
    </list>`;

test("the widget opens its configured action with the row as context", async () => {
    const calls = [];
    mockService("action", {
        doAction: (action, options) => calls.push([action, options]),
    });
    await mountView({ type: "list", resModel: "history.line", arch: ARCH });

    await click(".o_widget_price_history button:enabled");
    await animationFrame();

    expect(calls).toHaveLength(1);
    expect(calls[0][0]).toBe("some_module.some_action", {
        message: "the action comes from the view option, not from the component",
    });
    expect(calls[0][1].additionalContext).toEqual({
        default_line_id: 1,
        default_partner_id: 1,
        default_product_id: 1,
    });
});

test("a line with no product cannot open a price history", async () => {
    await mountView({ type: "list", resModel: "history.line", arch: ARCH });
    const buttons = [...document.querySelectorAll(".o_widget_price_history button")];
    expect(buttons).toHaveLength(2);
    expect(buttons[0].disabled).toBe(false);
    expect(buttons[1].disabled).toBe(true, {
        message: "there is no history of a product that is not set",
    });
});

test("the widget declares the fields it reads instead of relying on the view", () => {
    const widget = registry.category("view_widgets").get("price_history");
    const declared = widget.fieldDependencies.map((field) => field.name);
    expect(declared).toInclude("product_id");
    expect(declared).toInclude("partner_id");
});

test("the action is read from the view options", () => {
    const widget = registry.category("view_widgets").get("price_history");
    expect(widget.extractProps({ options: { action: "a.b" } })).toEqual({
        action: "a.b",
    });
});
