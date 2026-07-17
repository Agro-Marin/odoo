import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { expect, test } from "@odoo/hoot";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";

class Picking extends models.Model {
    json_popover = fields.Char();

    _records = [
        {
            id: 1,
            json_popover: JSON.stringify({
                popoverTemplate: "stock.PopoverStockRescheduling",
                late_elements: [
                    { id: 7, name: "WH/MO/00007", model: "mrp.production" },
                ],
                date_delay_alert: "07/01/2026",
            }),
        },
        {
            id: 2,
            json_popover: JSON.stringify({ color: "text-warning", icon: "fa-clock" }),
        },
    ];
}

defineModels([Picking]);
defineMailModels();

test("rescheduling popover mounts with default color/icon getters", async () => {
    // Locks the getter-based overrides: the previous setup() assignments threw
    // a TypeError (assignment through the base class' getter-only accessors),
    // crashing any view containing the widget.
    await mountView({
        type: "form",
        resModel: "picking",
        arch: `
            <form>
                <field name="json_popover" widget="stock_rescheduling_popover"/>
            </form>`,
        resId: 1,
    });
    expect(".fa-solid.fa-triangle-exclamation.text-danger").toHaveCount(1);
    await contains(".fa-solid.fa-triangle-exclamation").click();
    expect(".popover").toHaveCount(1);
    expect(".popover").toHaveText(/Planning Issue/);
    expect(".popover a").toHaveText("WH/MO/00007");
});

test("rescheduling popover honors custom color/icon and late-elements guard", async () => {
    await mountView({
        type: "form",
        resModel: "picking",
        arch: `
            <form>
                <field name="json_popover" widget="stock_rescheduling_popover"/>
            </form>`,
        resId: 2,
    });
    // Bare icon names get the fa-solid family; custom color wins over default.
    expect(".fa-solid.fa-clock.text-warning").toHaveCount(1);
    // Without late_elements, showPopup is a no-op.
    await contains(".fa-solid.fa-clock").click();
    expect(".popover").toHaveCount(0);
});
