import { expect, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";

import { definePosSelfModels } from "../data/generate_model_definitions.js";
import { getFilledSelfOrder, setupSelfPosEnv } from "../utils.js";

definePosSelfModels();

test("mounts in the self-order app, which starts no contextual_utils_service", async () => {
    const store = await setupSelfPosEnv();
    const order = await getFilledSelfOrder(store);

    await mountWithCleanup(OrderReceipt, { props: { order } });

    expect(".pos-receipt").toHaveCount(1);
    expect(queryOne(".receipt-total .pos-receipt-right-align").textContent).toBe(
        order.currencyDisplayPriceIncl,
    );
});
