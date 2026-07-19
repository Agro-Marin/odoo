import { expect, test } from "@odoo/hoot";
import {
    getFilledSelfOrder,
    setupSelfPosEnv,
} from "@pos_self_order/../tests/unit/utils";

import { definePosOnlinePaymentSelfOrderModels } from "../data/generate_model_definitions.js";

definePosOnlinePaymentSelfOrderModels();

test("sendDraftOrderToServer updateLastOrderChange", async () => {
    const store = await setupSelfPosEnv();
    const order = await getFilledSelfOrder(store);

    store.config.self_ordering_mode = "mobile";
    const product4 = store.models["product.template"].get(11);
    await store.addToCart(product4, 1, "");
    await store.sendDraftOrderToServer();
    expect(Object.keys(order.last_order_preparation_change.lines)).toHaveLength(0);

    store.config.self_ordering_pay_after = "meal";
    const product3 = store.models["product.template"].get(10);
    await store.addToCart(product3, 1, "");
    await store.sendDraftOrderToServer();
    expect(Object.keys(order.last_order_preparation_change.lines)).toHaveLength(4);
});
