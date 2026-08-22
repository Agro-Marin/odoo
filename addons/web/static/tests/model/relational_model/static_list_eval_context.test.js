// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    defineModels,
    fields,
    findComponent,
    models,
    mountView,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { RelationalRecord } from "@web/model/relational_model/record";
import { FormController } from "@web/views/form/form_controller";

class Order extends models.Model {
    name = fields.Char();
    line_ids = fields.One2many({ relation: "order.line" });
    _records = [{ id: 1, name: "o1", line_ids: [1, 2, 3] }];
}

class OrderLine extends models.Model {
    _name = "order.line";
    qty = fields.Integer();
    note = fields.Char();
    _records = [
        { id: 1, qty: 1, note: "a" },
        { id: 2, qty: 2, note: "b" },
        { id: 3, qty: 3, note: "c" },
    ];
}

defineModels([Order, OrderLine]);

describe.current.tags("desktop");

function trackEvalContext() {
    const calls = {};
    patchWithCleanup(RelationalRecord.prototype, {
        _setEvalContext() {
            calls[this.resModel] = (calls[this.resModel] || 0) + 1;
            return super._setEvalContext(...arguments);
        },
    });
    return calls;
}

async function getRoot() {
    const view = await mountView({
        type: "form",
        resModel: "order",
        resId: 1,
        arch: `
            <form>
                <field name="name"/>
                <field name="line_ids">
                    <list editable="bottom">
                        <field name="qty"/>
                        <field name="note"/>
                    </list>
                </field>
            </form>`,
    });
    const form = findComponent(view, (c) => c instanceof FormController);
    return form.model.root;
}

test(`editing an unrelated parent field does not recompute sub-record eval contexts`, async () => {
    const root = await getRoot();
    const calls = trackEvalContext();

    await root.update({ name: "o2" });

    expect(calls["order.line"] || 0).toBe(0);
    expect(calls["order"] || 0).toBeGreaterThan(0);
});

test(`editing a parent field the x2many context depends on still recomputes sub-records`, async () => {
    const view = await mountView({
        type: "form",
        resModel: "order",
        resId: 1,
        arch: `
            <form>
                <field name="name"/>
                <field name="line_ids" context="{'special_note': name}">
                    <list editable="bottom">
                        <field name="qty"/>
                        <field name="note"/>
                    </list>
                </field>
            </form>`,
    });
    const form = findComponent(view, (c) => c instanceof FormController);
    const root = form.model.root;
    const calls = trackEvalContext();

    await root.update({ name: "o2" });

    expect(calls["order.line"] || 0).toBeGreaterThan(0);
});
