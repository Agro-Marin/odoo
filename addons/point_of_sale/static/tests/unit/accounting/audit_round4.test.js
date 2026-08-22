import { expect, test } from "@odoo/hoot";

import { definePosModels } from "../data/generate_model_definitions.js";
import { setupPosEnv } from "../utils.js";
import { getFilledOrderForPriceCheck, prepareRoundingVals } from "./utils.js";

definePosModels();

test("F2: setOrderPrices writes the post-rounding total into amount_total", async () => {
    const store = await setupPosEnv();
    const { cashPm } = prepareRoundingVals(store, 0.05, "HALF-UP", false);
    const order = await getFilledOrderForPriceCheck(store);
    order.addPaymentline(cashPm);
    order.payment_ids[0].setAmount(order.totalDue);
    order.setOrderPrices();

    expect(order.priceIncl).toBe(52.54);
    expect(order.totalDue).toBe(52.55);
    expect(order.amount_total).toBe(52.55);
    expect(order.amount_total).toBe(order.amount_paid);
});

test("F4: change is not cash-rounded when the order itself is not rounded", async () => {
    const store = await setupPosEnv();
    const { cardPm } = prepareRoundingVals(store, 0.05, "HALF-UP", true);
    const order = await getFilledOrderForPriceCheck(store);
    order.addPaymentline(cardPm);
    order.payment_ids[0].setAmount(60.0);
    order.setOrderPrices();

    expect(order.orderIsRounded).toBe(false);
    expect(order.totalDue).toBe(52.54);
    expect(order.appliedRounding).toBe(0);
    expect(order.shouldRoundChange).toBe(false);
    expect(Math.abs(order.change)).toBe(7.46);
});

test("F5: combo parent displayPrice carries the order sign on a refund", async () => {
    const store = await setupPosEnv();
    const models = store.models;
    const data = models.loadConnectedData({
        "pos.order": [
            { id: 2, name: "Combo order", is_refund: true, lines: [2, 3, 4] },
        ],
        "pos.order.line": [
            {
                id: 2,
                order_id: 2,
                product_id: 7,
                price_unit: 0.0,
                qty: -1,
                combo_line_ids: [3, 4],
                tax_ids: [],
            },
            {
                id: 3,
                order_id: 2,
                product_id: 8,
                price_unit: 1,
                qty: -2,
                combo_parent_id: 2,
                tax_ids: [],
            },
            {
                id: 4,
                order_id: 2,
                product_id: 10,
                price_unit: 8,
                qty: -1,
                combo_parent_id: 2,
                tax_ids: [],
            },
        ],
    });
    const [parent, child1, child2] = data["pos.order.line"];
    const order = data["pos.order"][0];

    expect(order.orderSign).toBe(-1);
    expect(child1.displayPrice).toBe(2);
    expect(child2.displayPrice).toBe(8);
    expect(parent.displayPrice).toBe(10);
    expect(parent.displayPrice).toBe(child1.displayPrice + child2.displayPrice);
});

test("F6: discount_amount follows the display mode and the order sign", async () => {
    const store = await setupPosEnv();
    store.config.iface_tax_included = "subtotal";
    const order = await getFilledOrderForPriceCheck(store);
    const line = order.lines[0];
    line.setDiscount(10);

    expect(line.displayPriceNoDiscount).toBe(1000);
    expect(line.displayPrice).toBe(900);
    expect(line.prices.discount_amount).toBe(100);
    expect(order.getTotalDiscount()).toBe(100);
});
