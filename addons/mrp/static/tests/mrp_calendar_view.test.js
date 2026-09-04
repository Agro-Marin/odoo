import { defineMrpModels, MrpProduction } from "@mrp/../tests/mrp_test_helpers";
import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { mockDate } from "@odoo/hoot-mock";
import { mountView, onRpc } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineMrpModels();

const ARCH = `
    <calendar js_class="mrp_calendar" date_start="date_start" date_stop="date_end"
              string="Manufacturing Orders" event_limit="5" quick_create="0" mode="week">
        <field name="product_id"/>
        <field name="product_qty"/>
        <field name="product_uom_id" invisible="1"/>
    </calendar>`;

const CARD = ".o_event[data-event-id='1']";

beforeEach(() => {
    mockDate("2026-01-07 12:00:00", +0);

    MrpProduction._records = [
        {
            id: 1,
            name: "WH/MO/00001",
            display_name: "WH/MO/00001",
            date_start: "2026-01-07 08:00:00",
            date_end: "2026-01-07 10:00:00",
            product_id: 1,
            product_qty: 5,
            product_uom_id: 1,
        },
    ];

    onRpc("has_access", () => true);
});

test("the week card says which product is being made, and how much", async () => {
    await mountView({ resModel: "mrp.production", type: "calendar", arch: ARCH });

    expect(CARD).toHaveText(/WH\/MO\/00001/);
    expect(CARD).toHaveText(/Test Product/);
    expect(CARD).toHaveText(/5\s*Units/);
});

test("an order with no product still shows its reference alone", async () => {
    MrpProduction._records[0].product_id = false;
    MrpProduction._records[0].product_qty = 0;
    await mountView({ resModel: "mrp.production", type: "calendar", arch: ARCH });

    expect(CARD).toHaveText(/WH\/MO\/00001/);
    expect(CARD).not.toHaveText(/Units/);
});
