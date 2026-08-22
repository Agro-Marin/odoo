import { describe, expect, test } from "@odoo/hoot";
import { PosOrderLineRefund } from "@point_of_sale/app/models/pos_order_line_refund";
import { computeComboItems } from "@point_of_sale/app/models/utils/compute_combo_items";

import { definePosModels } from "../data/generate_model_definitions.js";
import { getFilledOrder, setupPosEnv } from "../utils.js";

definePosModels();

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
        expect(Number.isNaN(refund.maxQty)).toBe(false);
        expect(refund.maxQty).toBe(line.qty - line.refundedQty);
    });

    test("C10: floatingOrderName does not throw without a tracking_number", async () => {
        const store = await setupPosEnv();
        const order = store.addNewOrder();
        order.floating_order_name = false;
        order.tracking_number = undefined;
        expect(() => order.floatingOrderName).not.toThrow();
        expect(order.floatingOrderName).toBe("");
    });
});

describe("audit regression fixes (pass 2)", () => {
    test("P2: combo with all-zero base_price yields finite (non-NaN) prices", () => {
        const ProductPrice = { round: (x) => x };
        const parentProduct = { getPrice: () => 100 };
        const mkConf = () => ({
            combo_item_id: { combo_id: { base_price: 0 }, extra_price: 0 },
            qty: 1,
            parentQty: 1,
            configuration: {},
        });
        const comboItems = computeComboItems(
            parentProduct,
            [mkConf(), mkConf()],
            null,
            [],
            {},
            [],
            ProductPrice,
        );
        expect(comboItems.length).toBe(2);
        for (const item of comboItems) {
            expect(Number.isFinite(item.price_unit)).toBe(true);
        }
        const total = comboItems.reduce((s, i) => s + i.price_unit * i.qty, 0);
        expect(total).toBe(100);
    });

    test("P2: getScreenData keeps an explicitly saved screen with payment lines", async () => {
        const store = await setupPosEnv();
        const order = await getFilledOrder(store);
        order.addPaymentline(store.models["pos.payment.method"].get(1));
        expect(order.payment_ids.length).toBeGreaterThan(0);
        expect(order.finalized).toBe(false);

        order.setScreenData({ name: "TipScreen" });
        expect(order.getScreenData().name).toBe("TipScreen");
    });

    test("P2: serializeForORM defers the dirty cleanup until commit", async () => {
        const store = await setupPosEnv();
        const order = await getFilledOrder(store);
        expect(order.isDirty()).toBe(true);

        const clearActions = [];
        store.models.serializeForORM(order, { deferClear: true, clearActions });
        expect(order.isDirty()).toBe(true);
        expect(clearActions.length).toBeGreaterThan(0);

        clearActions.forEach((fn) => fn());
        expect(order.isDirty()).toBe(false);
    });

    test("P2: serializeForORM without deferClear clears _dirty immediately", async () => {
        const store = await setupPosEnv();
        const order = await getFilledOrder(store);
        expect(order.isDirty()).toBe(true);
        store.models.serializeForORM(order);
        expect(order.isDirty()).toBe(false);
    });
});
