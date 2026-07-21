// @ts-check

/**
 * Behavioral regression test for the command engine's UPDATE case
 * (static_list_command_engine.js): server-originated onchange commands must
 * flow through the SERVER slot of ``record._applyChanges`` so the child
 * record's ``_textValues`` keeps the RAW server value.
 *
 * The engine used to pre-parse the UPDATE payload and pass it as the USER
 * slot, where the char/text deserializer's ``false → ""`` mapping was stored
 * in ``_textValues``. The row eval context builds char/text entries from
 * ``_textValues`` (record_value_transforms.js — computeDataContext), so a
 * sibling-cell modifier like ``[("field", "=", False)]`` mis-evaluated
 * (``"" == False`` is False in py_js) until the record was reloaded. Parent
 * records never had the bug — only command-engine-applied child updates.
 */

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
    // Marks `name` with the onChange flag; the actual response is mocked via
    // onRpc("onchange") in the test (test-local, no mock-server change).
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
    // The parent onchange rewrites a loaded o2m line, clearing its `func`
    // char — this is applied through the command engine's UPDATE case.
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

    // Control: func is set, so the modifier on the sibling cell is inactive.
    expect(".o_data_row .o_data_cell[name=note]").not.toHaveClass(
        "o_readonly_modifier",
    );

    await contains(".o_field_widget[name=name] input").edit("trigger");

    // The server set func to false: the sibling cell's `func == False`
    // modifier must now evaluate true. With "" in _textValues it stayed
    // inactive until reload.
    expect(".o_data_row .o_data_cell[name=note]").toHaveClass("o_readonly_modifier");
});
