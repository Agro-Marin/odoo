import { expect, test } from "@odoo/hoot";

import { definePosModels } from "../data/generate_model_definitions.js";
import { getFilledOrder, setupPosEnv } from "../utils.js";

definePosModels();

test("pay() resets a wedged terminal line to 'retry' and rethrows on failure", async () => {
    const store = await setupPosEnv();
    const order = await getFilledOrder(store);
    const paymentMethod = store.models["pos.payment.method"].get(1);
    // Give the method a terminal whose request rejects (network/RPC failure).
    paymentMethod.payment_terminal = {
        sendPaymentRequest: async () => {
            throw new Error("terminal offline");
        },
    };
    const { data: payment } = order.addPaymentline(paymentMethod);

    await expect(payment.pay()).rejects.toThrow("terminal offline");
    // The line must NOT stay in "waiting" (which renders no Retry button and
    // blocks adding another electronic payment); it must be actionable again.
    expect(payment.getPaymentStatus()).toBe("retry");
});

test("pay() marks the line 'done' when the terminal succeeds", async () => {
    const store = await setupPosEnv();
    const order = await getFilledOrder(store);
    const paymentMethod = store.models["pos.payment.method"].get(1);
    paymentMethod.payment_terminal = {
        sendPaymentRequest: async () => true,
    };
    const { data: payment } = order.addPaymentline(paymentMethod);

    const ok = await payment.pay();
    expect(ok).toBe(true);
    expect(payment.getPaymentStatus()).toBe("done");
});
