// @ts-check

import { expect, test } from "@odoo/hoot";
import { click } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import {
    defineModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";

class Partner extends models.Model {
    bar = fields.Boolean({ string: "Bar field" });
    foo = fields.Boolean();

    _records = [{ id: 1, bar: true, foo: false }];
}

defineModels([Partner]);

test("BooleanIcon field in form view", async () => {
    await mountView({
        resModel: "partner",
        resId: 1,
        type: "form",
        arch: `
            <form>
                <field name="bar" widget="boolean_icon" options="{'icon': 'fa-recycle'}" />
                <field name="foo" widget="boolean_icon" options="{'icon': 'fa-trash'}" />
            </form>`,
    });
    expect(".o_field_boolean_icon button").toHaveCount(2);
    expect("[name='bar'] button").toHaveAttribute("data-tooltip", "Bar field");
    expect("[name='bar'] button").toHaveClass("btn-primary fa-recycle");
    expect("[name='foo'] button").toHaveClass("btn-outline-secondary fa-trash");

    await click("[name='bar'] button");
    await animationFrame();
    expect("[name='bar'] button").toHaveClass("btn-outline-secondary fa-recycle");
});

test("BooleanIcon field readonly in form view", async () => {
    await mountView({
        resModel: "partner",
        resId: 1,
        type: "form",
        arch: `
            <form>
                <field name="bar" widget="boolean_icon" readonly="1" options="{'icon': 'fa-recycle'}" />
            </form>`,
    });
    expect("[name='bar'] button").toHaveAttribute("disabled");
    expect("[name='bar'] button").toHaveClass("btn-primary");

    await click("[name='bar'] button");
    await animationFrame();
    expect("[name='bar'] button").toHaveClass("btn-primary", {
        message: "a readonly boolean icon must not flip on click",
    });
    expect(".o_form_status_indicator_buttons").not.toBeVisible({
        message: "the record must stay clean",
    });
});
