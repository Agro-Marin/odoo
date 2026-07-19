import { expect, test } from "@odoo/hoot";

import { definePosModels } from "../data/generate_model_definitions.js";
import { getFilledOrder, setupPosEnv } from "../utils.js";

definePosModels();

// `clickSaveOrder` ("Save order for later") pushed the order with an explicit
// `{orders: [...]}` argument, which bypasses the pendingOrder queue entirely:
// `_syncAllOrders` only consults `getPendingOrder()` when no explicit list is
// given. It also never awaited the push and showed a success notification
// unconditionally. Offline, `_syncAllOrders` *returns* (does not throw) a
// ConnectionLostError, so the cashier saw "Order saved for later" while the
// order was neither on the server nor queued for any later retry — the edits
// survived only until the next reload re-derived the queue from the dirty flags.
test("clickSaveOrder queues the order for retry when offline", async () => {
    const store = await setupPosEnv();
    const order = await getFilledOrder(store);

    // Order starts queued (getFilledOrder marks it pending); flush that so we
    // observe only what clickSaveOrder itself does.
    await store.syncAllOrders();
    store.clearPendingOrder();

    // Make it dirty again, then go offline.
    order.update({ general_customer_note: "saved while offline" });
    expect(order.isDirty()).toBe(true);
    store.data.network.offline = true;

    store.setOrder(order);
    store.clickSaveOrder();
    await Promise.resolve();

    // The order still has unsynced local edits, so it MUST be in the pending
    // queue for the reconnect sync to pick up.
    const { orderToCreate, orderToUpdate } = store.getPendingOrder();
    expect([...orderToCreate, ...orderToUpdate].map((o) => o.uuid)).toInclude(
        order.uuid,
        { message: "offline-saved order must remain queued for a later sync" },
    );
});
