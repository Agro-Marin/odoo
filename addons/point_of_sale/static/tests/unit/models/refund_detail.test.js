import { describe, expect, test } from "@odoo/hoot";
import { PosOrderLineRefund } from "@point_of_sale/app/models/pos_order_line_refund";

import { definePosModels } from "../data/generate_model_definitions.js";
import { getFilledOrder, setupPosEnv } from "../utils.js";

definePosModels();

/** The ticket screen's own shape: the detail is stored on the order that owns
 * the line being refunded, keyed by that line's uuid. */
async function anOrderBeingRefunded(store) {
    const original = await getFilledOrder(store);
    const originalLine = original.lines[0];
    const detail = new PosOrderLineRefund(
        { line_uuid: originalLine.uuid, qty: 1 },
        store.models,
    );
    original.uiState.lineToRefund[originalLine.uuid] = detail;

    const refundOrder = store.addNewOrder();
    const refundLine = store.models["pos.order.line"].create({
        order_id: refundOrder,
        product_id: originalLine.product_id,
        qty: -1,
        price_unit: originalLine.price_unit,
        refunded_orderline_id: originalLine,
    });
    return { original, originalLine, refundOrder, refundLine };
}

describe("a refund detail lives on the refunded order", () => {
    test("removing the refund line clears it", async () => {
        const store = await setupPosEnv();
        const { original, originalLine, refundOrder, refundLine } =
            await anOrderBeingRefunded(store);
        expect(originalLine.uuid in original.uiState.lineToRefund).toBe(true);

        refundOrder.removeOrderline(refundLine);

        expect(originalLine.uuid in original.uiState.lineToRefund).toBe(false);
    });

    test("setQuantity finds the detail without merging every order's map", async () => {
        const store = await setupPosEnv();
        const { refundLine } = await anOrderBeingRefunded(store);
        const refusal = refundLine.setQuantity(2);
        expect(refusal).not.toBe(true);
        expect(refusal.title).toBeOfType("string");
        expect(refundLine.setQuantity(-1)).toBe(true);
    });
});
