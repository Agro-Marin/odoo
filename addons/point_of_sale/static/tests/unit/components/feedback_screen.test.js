import { expect, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import { FeedbackScreen } from "@point_of_sale/app/screens/feedback_screen/feedback_screen";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";

import { definePosModels } from "../data/generate_model_definitions.js";
import { getFilledOrder, setupPosEnv } from "../utils.js";

definePosModels();

test("the amount paid is shown with its currency", async () => {
    const store = await setupPosEnv();
    const order = await getFilledOrder(store);
    // `amount_total` is a server field, written client-side by
    // `setOrderPrices()` when the order is validated -- which is what happens
    // before this screen is ever shown.
    order.setOrderPrices();
    await mountWithCleanup(FeedbackScreen, {
        props: { orderUuid: order.uuid },
    });
    // PriceFormatter splits the symbol off to render it smaller: handing it a
    // bare number leaves that span empty and the customer reading a figure
    // with no currency on it.
    expect(queryOne(".feedback-screen .amount")).toHaveText("$17.85");
});
