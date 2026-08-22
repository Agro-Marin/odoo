import "@sale/interactions/portal_prepayment";

import { describe, expect, test } from "@odoo/hoot";
import {
    setupInteractionWhiteList,
    startInteractions,
} from "@web/../tests/public/helpers";

setupInteractionWhiteList("sale.portal_prepayment");
describe.current.tags("interaction_dev");

const template = `
    <div class="o_portal_sale_sidebar" data-order-amount-total="100">
        <button name="o_sale_portal_amount_prepayment_button" class="btn btn-light active">Down payment</button>
        <button name="o_sale_portal_amount_total_button" class="btn btn-light">Full amount</button>
        <span id="o_sale_portal_use_amount_prepayment">by paying a down payment</span>
        <span id="o_sale_portal_use_amount_total">by paying the full amount</span>
    </div>
`;

test("interaction starts on .o_portal_sale_sidebar", async () => {
    const { core } = await startInteractions(template);
    expect(core.interactions).toHaveLength(1);
});

test("defaults to down payment, resolving buttons within the sidebar", async () => {
    await startInteractions(template);
    expect(`button[name="o_sale_portal_amount_prepayment_button"]`).toHaveClass(
        "active",
    );
    expect(`button[name="o_sale_portal_amount_total_button"]`).not.toHaveClass(
        "active",
    );
    expect("#o_sale_portal_use_amount_prepayment").not.toHaveClass("d-none");
    expect("#o_sale_portal_use_amount_total").toHaveClass("d-none");
});
