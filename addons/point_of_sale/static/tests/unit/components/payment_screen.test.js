import { animationFrame, expect, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";

import { definePosModels } from "../data/generate_model_definitions.js";
import { expectFormattedPrice, getFilledOrder, setupPosEnv } from "../utils.js";

definePosModels();

test("sendPaymentCancel restores the line status when the terminal throws", async () => {
    const store = await setupPosEnv();
    const order = await getFilledOrder(store);
    const pm = store.models["pos.payment.method"].getFirst();
    pm.payment_terminal = {
        sendPaymentCancel: async () => {
            throw new Error("terminal offline");
        },
    };
    const comp = await mountWithCleanup(PaymentScreen, {
        props: { orderUuid: order.uuid },
    });
    const { data: line } = order.addPaymentline(pm);
    line.setPaymentStatus("waitingCard");

    await comp.sendPaymentCancel(line);
    // Must not be stranded in "waitingCancel" (unrecoverable + unhandled
    // rejection); the prior status is restored so cancel can be retried.
    expect(line.getPaymentStatus()).toBe("waitingCard");
});

test("sendPaymentReverse restores the line status when the terminal throws", async () => {
    const store = await setupPosEnv();
    const order = await getFilledOrder(store);
    const pm = store.models["pos.payment.method"].getFirst();
    pm.payment_terminal = {
        sendPaymentReversal: async () => {
            throw new Error("terminal offline");
        },
    };
    const comp = await mountWithCleanup(PaymentScreen, {
        props: { orderUuid: order.uuid },
    });
    const { data: line } = order.addPaymentline(pm);
    line.setPaymentStatus("done");

    await comp.sendPaymentReverse(line);
    expect(line.getPaymentStatus()).toBe("done");
});

test("Change always incl", async () => {
    const store = await setupPosEnv();
    const order = await getFilledOrder(store);
    const firstPm = store.models["pos.payment.method"].getFirst();
    order.config.iface_tax_included = "total";
    const comp = await mountWithCleanup(PaymentScreen, {
        props: { orderUuid: order.uuid },
    });
    await comp.addNewPaymentLine(firstPm);
    order.payment_ids[0].setAmount(20);
    await animationFrame();
    const total = queryOne(".amount");
    expectFormattedPrice(total.attributes.amount.value, "$ -2.15");
    order.config.iface_tax_included = "subtotal";
    await animationFrame();
    const subtotal = queryOne(".amount");
    expectFormattedPrice(subtotal.attributes.amount.value, "$ -2.15");
});
