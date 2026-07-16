import { expect, test } from "@odoo/hoot";
import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";

import { definePosModels } from "../data/generate_model_definitions.js";
import { getFilledOrder, setupPosEnv } from "../utils.js";

definePosModels();

test("validateOrder", async () => {
    const store = await setupPosEnv();
    const order = await getFilledOrder(store);
    const fastPaymentMethod = order.config.fast_payment_method_ids[0];
    const validation = new OrderPaymentValidation({
        pos: store,
        orderUuid: store.getOrder().uuid,
        fastPaymentMethod: fastPaymentMethod,
    });
    await validation.validateOrder(false);
    expect(order.payment_ids[0].payment_method_id).toEqual(fastPaymentMethod);
    expect(order.state).toBe("paid");
    expect(order.amount_paid).toBe(17.85);
});
test("validation is refused while a terminal payment is in flight", async () => {
    const store = await setupPosEnv();
    const order = await getFilledOrder(store);
    const cashMethod = store.models["pos.payment.method"].find(
        (pm) => pm.is_cash_count,
    );
    // Simulate an electronic line the terminal is still processing, covered by
    // a cash line for the full amount (the exact state that used to validate
    // and silently delete the live terminal transaction). Lines are created
    // before the "waiting" status is set because addPaymentline itself refuses
    // to add lines while an electronic payment is in progress.
    const terminalLine = order.addPaymentline(cashMethod).data;
    const cashLine = order.addPaymentline(cashMethod).data;
    terminalLine.setAmount(0);
    cashLine.setAmount(order.totalDue);
    terminalLine.setPaymentStatus("waiting");

    const validation = new OrderPaymentValidation({
        pos: store,
        orderUuid: order.uuid,
    });
    expect(await validation.isOrderValid(false)).toBe(false);
    // Once the terminal transaction completes, validation may proceed.
    terminalLine.setPaymentStatus("done");
    expect(await validation.isOrderValid(false)).toBe(true);
});

test("isOrderValid", async () => {
    const store = await setupPosEnv();
    const order = store.addNewOrder();
    order.setToInvoice(true);
    const validation = new OrderPaymentValidation({
        pos: store,
        orderUuid: store.getOrder().uuid,
    });
    const isOrderValid = await validation.isOrderValid(false);
    expect(order.lines).toHaveLength(0);
    expect(isOrderValid).toBe(false); // The order cannot be invoiced if the order line count is zero.
});
