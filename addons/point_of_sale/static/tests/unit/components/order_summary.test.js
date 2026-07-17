import { animationFrame, expect, test } from "@odoo/hoot";
import { queryAll, queryOne } from "@odoo/hoot-dom";
import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";

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
    // A fresh decrease line was created and remembered on the saved line.
    expect(order.lines.length).toBe(linesBefore + 1);
    expect(selectedLine.uiState.decreaseLineUuid).toBe(first.uuid);

    // A second decrease of the same line must reuse that line, not create
    // another (the old total-matching logic spawned a new one every time).
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
    // The "-0" negation branch used to dereference the selected line before
    // any null check — the numpad +/- key crashed the screen right after
    // entering it (deselection is the default state).
    await orderSummary.updateSelectedOrderline({ buffer: "-0", key: "-" });
    expect(order.getSelectedOrderline()).toBe(undefined);
});
