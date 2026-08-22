// @ts-check

import { expect, test } from "@odoo/hoot";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
    onRpc,
} from "@web/../tests/web_test_helpers";

class Order extends models.Model {
    name = fields.Char();
    line_ids = fields.One2many({ relation: "order.line" });
    _onChanges = {
        name() {},
    };
    _records = [{ id: 1, name: "o1", line_ids: [1] }];
}

class OrderLine extends models.Model {
    _name = "order.line";
    func = fields.Char();
    note = fields.Char();
    _records = [{ id: 1, func: "compute", note: "hello" }];
}

defineModels([Order, OrderLine]);

test(`onchange UPDATE clearing a char keeps false (not "") in the row eval context`, async () => {
    onRpc("onchange", () => ({
        value: { line_ids: [[1, 1, { func: false }]] },
    }));
    await mountView({
        type: "form",
        resModel: "order",
        resId: 1,
        arch: `
            <form>
                <field name="name"/>
                <field name="line_ids">
                    <list editable="bottom">
                        <field name="func"/>
                        <field name="note" readonly="func == False"/>
                    </list>
                </field>
            </form>`,
    });

    expect(".o_data_row .o_data_cell[name=note]").not.toHaveClass(
        "o_readonly_modifier",
    );

    await contains(".o_field_widget[name=name] input").edit("trigger");

    expect(".o_data_row .o_data_cell[name=note]").toHaveClass("o_readonly_modifier");
});
