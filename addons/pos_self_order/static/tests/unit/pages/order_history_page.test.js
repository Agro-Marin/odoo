import { expect, test } from "@odoo/hoot";
import { OrdersHistoryPage } from "@pos_self_order/app/pages/order_history_page/order_history_page";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";

import { definePosSelfModels } from "../data/generate_model_definitions.js";
import { getFilledSelfOrder, setupSelfPosEnv } from "../utils.js";

definePosSelfModels();

test("getNameAndDescription", async () => {
    const store = await setupSelfPosEnv();
    const order = await getFilledSelfOrder(store);
    const [line1, line2] = order.lines;
    const comp = await mountWithCleanup(OrdersHistoryPage, { props: {} });

    expect(comp.getNameAndDescription(line1)).toMatchObject({
        productName: "TEST",
        attributes: "",
    });
    expect(comp.getNameAndDescription(line2)).toMatchObject({
        productName: "TEST 2",
        attributes: "",
    });
});
