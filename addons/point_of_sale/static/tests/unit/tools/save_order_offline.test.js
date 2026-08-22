import { expect, test } from "@odoo/hoot";

import { definePosModels } from "../data/generate_model_definitions.js";
import { getFilledOrder, setupPosEnv } from "../utils.js";

definePosModels();

test("clickSaveOrder queues the order for retry when offline", async () => {
    const store = await setupPosEnv();
    const order = await getFilledOrder(store);

    await store.syncAllOrders();
    store.clearPendingOrder();

    order.update({ general_customer_note: "saved while offline" });
    expect(order.isDirty()).toBe(true);
    store.data.network.offline = true;

    store.setOrder(order);
    store.clickSaveOrder();
    await Promise.resolve();

    const { orderToCreate, orderToUpdate } = store.getPendingOrder();
    expect([...orderToCreate, ...orderToUpdate].map((o) => o.uuid)).toInclude(
        order.uuid,
        { message: "offline-saved order must remain queued for a later sync" },
    );
});
