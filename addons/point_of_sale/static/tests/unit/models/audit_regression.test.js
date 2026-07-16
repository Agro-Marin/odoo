import { test, expect, describe } from "@odoo/hoot";
import { setupPosEnv, getFilledOrder } from "../utils.js";
import { definePosModels } from "../data/generate_model_definitions.js";
import { PosOrderLineRefund } from "@point_of_sale/app/models/pos_order_line_refund";
import { computeComboItems } from "@point_of_sale/app/models/utils/compute_combo_items";

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

// Regression tests for the second JS audit pass.
describe("audit regression fixes (pass 2)", () => {
    test("P2: combo with all-zero base_price yields finite (non-NaN) prices", () => {
        // When every selected combo choice has base_price 0 (the price lives on
        // the parent), originalTotal was 0 and `base_price * lst / originalTotal`
        // computed 0/0 = NaN — poisoning the order total and serializing NaN to
        // the backend. The divisor is now guarded.
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
            null, // pricelist (mocked getPrice ignores it)
            [], // decimalPrecision (currency_id below provides ProductPrice)
            {}, // productTemplateAttributeValueById
            [], // childLineExtra
            ProductPrice, // currency_id → used as ProductPrice
        );
        expect(comboItems.length).toBe(2);
        for (const item of comboItems) {
            expect(Number.isFinite(item.price_unit)).toBe(true);
        }
        // The whole parent price is still distributed (onto the last line).
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
        // Pre-fix an unconditional payment-line default ran after the
        // `if (!screen)` block, forcing PaymentScreen and discarding the saved
        // screen.
        expect(order.getScreenData().name).toBe("TipScreen");
    });

    test("P2: serializeForORM defers the dirty cleanup until commit", async () => {
        const store = await setupPosEnv();
        const order = await getFilledOrder(store);
        expect(order.isDirty()).toBe(true);

        // deferClear must not clear _dirty during serialization, so a sync that
        // throws (offline) keeps the order's pending edits for the retry instead
        // of consuming them into a payload the server never received.
        const clearActions = [];
        store.models.serializeForORM(order, { deferClear: true, clearActions });
        expect(order.isDirty()).toBe(true);
        expect(clearActions.length).toBeGreaterThan(0);

        // pos_store runs these only after the RPC succeeds.
        clearActions.forEach((fn) => fn());
        expect(order.isDirty()).toBe(false);
    });

    test("P2: serializeForORM without deferClear clears _dirty immediately", async () => {
        const store = await setupPosEnv();
        const order = await getFilledOrder(store);
        expect(order.isDirty()).toBe(true);
        // Control: the default (non-deferred) path is unchanged — clears inline.
        store.models.serializeForORM(order);
        expect(order.isDirty()).toBe(false);
    });
});
