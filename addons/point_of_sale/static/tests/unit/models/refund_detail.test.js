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

        // It used to look the key up in `this.uiState.lineToRefund` -- the
        // REFUNDING order's map -- where a refunded line's uuid can never be,
        // because the only writer keys each order's map by its own lines. So the
        // guard was always false, the delete never ran, and the original order
        // went on reporting the quantity as still to refund.
        expect(originalLine.uuid in original.uiState.lineToRefund).toBe(false);
    });

    test("setQuantity finds the detail without merging every order's map", async () => {
        const store = await setupPosEnv();
        const { refundLine } = await anOrderBeingRefunded(store);
        // a positive quantity on a refund line is refused
        const refusal = refundLine.setQuantity(2);
        expect(refusal).not.toBe(true);
        expect(refusal.title).toBeOfType("string");
        // and a negative one within the refundable quantity is accepted
        expect(refundLine.setQuantity(-1)).toBe(true);
    });
});
