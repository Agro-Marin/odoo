import { test, expect, describe } from "@odoo/hoot";
import { setupPosEnv, getFilledOrder } from "../utils.js";
import { definePosModels } from "../data/generate_model_definitions.js";
import { PosOrderLineRefund } from "@point_of_sale/app/models/pos_order_line_refund";

definePosModels();

// Regression tests for point_of_sale JS audit fixes. Each assertion fails
// against the pre-fix code and passes after the fix.

describe("audit regression fixes", () => {
    test("C3: PosOrderLineRefund.maxQty is the refundable qty, not NaN", async () => {
        const store = await setupPosEnv();
        const order = await getFilledOrder(store);
        const line = order.getOrderlines()[0];
        expect(line.qty).toBeGreaterThan(0);

        const refund = new PosOrderLineRefund(
            { line_uuid: line.uuid, qty: 0 },
            store.models,
        );
        // Pre-fix this read `this.refundedQty` (undefined) → NaN, which broke the
        // one-tap refund default (qty stayed 0 → nothing refunded).
        expect(Number.isNaN(refund.maxQty)).toBe(false);
        expect(refund.maxQty).toBe(line.qty - line.refundedQty);
    });

    test("C10: floatingOrderName does not throw without a tracking_number", async () => {
        const store = await setupPosEnv();
        const order = store.addNewOrder();
        order.floating_order_name = false;
        order.tracking_number = undefined;
        // Pre-fix `this.tracking_number.toString()` threw a TypeError.
        expect(() => order.floatingOrderName).not.toThrow();
        expect(order.floatingOrderName).toBe("");
    });
});
