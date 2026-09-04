import { animationFrame, expect, test } from "@odoo/hoot";
import { queryAll, queryOne } from "@odoo/hoot-dom";
import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";

import { getFilledOrderForPriceCheck } from "../accounting/utils.js";
import { definePosModels } from "../data/generate_model_definitions.js";
import { getFilledOrder, setupPosEnv } from "../utils.js";

definePosModels();

test("getNewLine", async () => {
    const store = await setupPosEnv();
    const order = await getFilledOrder(store);
    const orderSummary = await mountWithCleanup(OrderSummary, {});
    order.getSelectedOrderline().uiState.savedQuantity = 5;
    const newLine = orderSummary.getNewLine();
    expect(newLine.order_id.id).toBe(order.id);
    expect(newLine.qty).toBe(0);
});

test("getNewLine reuses the paired decrease line instead of spawning new ones", async () => {
    const store = await setupPosEnv();
    const order = await getFilledOrder(store);
    const orderSummary = await mountWithCleanup(OrderSummary, {});
    const selectedLine = order.getSelectedOrderline();
    selectedLine.uiState.savedQuantity = 5;
    const linesBefore = order.lines.length;

    const first = orderSummary.getNewLine();
    expect(order.lines.length).toBe(linesBefore + 1);
    expect(selectedLine.uiState.decreaseLineUuid).toBe(first.uuid);

    const second = orderSummary.getNewLine();
    expect(second.uuid).toBe(first.uuid);
    expect(order.lines.length).toBe(linesBefore + 1);
});

test("Display tax include/exclude subtotal label", async () => {
    const store = await setupPosEnv();
    const order = await getFilledOrder(store);

    order.config.iface_tax_included = "total";
    await mountWithCleanup(OrderSummary, {});
    const total = queryOne(".total");
    const subtotal = queryAll(".subtotal");
    expect(subtotal).toHaveLength(0);
    expect(total.innerHTML).toBe("$&nbsp;17.85");

    order.config.iface_tax_included = "subtotal";
    await animationFrame();
    const total2 = queryOne(".total");
    const subtotal2 = queryOne(".subtotal");
    expect(total2.innerHTML).toBe("$&nbsp;17.85");
    expect(subtotal2.innerHTML).toBe("$&nbsp;15.00");
});

test("+/- with no selected line does not crash", async () => {
    const store = await setupPosEnv();
    const order = await getFilledOrder(store);
    const orderSummary = await mountWithCleanup(OrderSummary, {});
    order.deselectOrderline();
    await orderSummary.updateSelectedOrderline({ buffer: "-0", key: "-" });
    expect(order.getSelectedOrderline()).toBe(undefined);
});

test("setLinePrice takes the price the cashier typed as the price the cashier sees", async () => {
    const store = await setupPosEnv();
    const order = await getFilledOrderForPriceCheck(store);
    const orderSummary = await mountWithCleanup(OrderSummary, {});
    order.config.iface_tax_included = "total";

    // lines[0] carries one 25% tax-excluded tax, qty 1, no discount. Typing
    // 125 must bill 125, so price_unit has to come out at 100.
    const singleTaxLine = order.lines[0];
    await orderSummary.setLinePrice(singleTaxLine, 125);
    expect(singleTaxLine.price_unit).toBe(100);
    expect(singleTaxLine.displayPrice).toBe(125);

    // lines[1] carries 15% + 25%, both tax-excluded.
    const multiTaxLine = order.lines[1];
    await orderSummary.setLinePrice(multiTaxLine, 140);
    expect(multiTaxLine.price_unit).toBe(100);
    expect(multiTaxLine.displayPrice).toBe(140);

    // The typed price is the price before discount, so setting a price does
    // not silently undo one.
    singleTaxLine.setDiscount(10);
    await orderSummary.setLinePrice(singleTaxLine, 110);
    expect(singleTaxLine.price_unit).toBe(88);
    expect(singleTaxLine.displayPrice).toBe(99);
});

test("setLinePrice keeps the typed price as price_unit on a tax-excluded register", async () => {
    const store = await setupPosEnv();
    const order = await getFilledOrderForPriceCheck(store);
    const orderSummary = await mountWithCleanup(OrderSummary, {});
    order.config.iface_tax_included = "subtotal";

    const line = order.lines[0];
    await orderSummary.setLinePrice(line, 125);
    expect(line.price_unit).toBe(125);
    expect(line.displayPrice).toBe(125);
});
