import { describe, expect, test } from "@odoo/hoot";
import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";
import { PosOrderLineRefund } from "@point_of_sale/app/models/pos_order_line_refund";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";

import { definePosModels } from "../data/generate_model_definitions.js";
import { getFilledOrder, setupPosEnv } from "../utils.js";

definePosModels();

async function aSelectedRefundLine(store) {
    const original = await getFilledOrder(store);
    const originalLine = original.lines[0];
    original.uiState.lineToRefund[originalLine.uuid] = new PosOrderLineRefund(
        { line_uuid: originalLine.uuid, qty: 1 },
        store.models,
    );

    const refundOrder = store.addNewOrder();
    const refundLine = store.models["pos.order.line"].create({
        order_id: refundOrder,
        product_id: originalLine.product_id,
        qty: -1,
        price_unit: originalLine.price_unit,
        refunded_orderline_id: originalLine,
    });
    refundOrder.selectOrderline(refundLine);
    return refundLine;
}

describe("a refused refund quantity reaches the cashier", () => {
    test("the numpad path reports the refusal", async () => {
        const store = await setupPosEnv();
        const refundLine = await aSelectedRefundLine(store);
        const component = await mountWithCleanup(OrderSummary, {});
        const dialogs = [];
        component.dialog = { add: (_, props) => dialogs.push(props) };

        store.numpadMode = "quantity";
        component._setValue(2);

        expect(refundLine.getQuantity()).toBe(-1);
        expect(dialogs).toHaveLength(1);
        expect(dialogs[0].title).toBe("Positive quantity not allowed");
    });

    test("the popup path reports it too", async () => {
        const store = await setupPosEnv();
        const refundLine = await aSelectedRefundLine(store);
        const component = await mountWithCleanup(OrderSummary, {});
        const dialogs = [];
        component.dialog = { add: (_, props) => dialogs.push(props) };

        await component.updateQuantityNumber(2);

        expect(refundLine.getQuantity()).toBe(-1);
        expect(dialogs).toHaveLength(1);
        expect(dialogs[0].title).toBe("Positive quantity not allowed");
    });
});
