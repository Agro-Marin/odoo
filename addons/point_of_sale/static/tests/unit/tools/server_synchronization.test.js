import { expect, test } from "@odoo/hoot";

import { definePosModels } from "../data/generate_model_definitions.js";
import { getFilledOrder, setupPosEnv } from "../utils.js";

definePosModels();

test("Related models must keep local records", async () => {
    const store = await setupPosEnv();
    const order = await getFilledOrder(store);
    const product = store.models["product.template"].get(8);
    expect(order.isSynced).toBe(false);
    expect(order.lines.every((l) => l.isSynced === true)).toBe(false);
    await store.syncAllOrders();
    expect(order.isSynced).toBe(true);
    expect(order.lines.every((l) => l.isSynced === true)).toBe(true);
    await store.addLineToOrder(
        {
            product_tmpl_id: product,
            qty: 1,
        },
        order,
    );
    expect(order.lines.every((l) => l.isSynced === true)).toBe(false);

    // Download the same order from server, the local unsynced line must be kept
    await store.data.loadServerOrders([["id", "=", order.id]]);
    expect(order.lines.every((l) => l.isSynced === true)).toBe(false);
});

test("Check behavior when deleting records", async () => {
    const store = await setupPosEnv();
    const order = await getFilledOrder(store);
    expect(order.isSynced).toBe(false);
    expect(order.lines.every((l) => l.isSynced === true)).toBe(false);
    await store.syncAllOrders();
    expect(order.isSynced).toBe(true);
    expect(order.lines.every((l) => l.isSynced === true)).toBe(true);
    order.removeOrderline(order.lines[0]);
    expect(order.lines).toHaveLength(1);

    // Device sync is server-authoritative: downloading the same order from
    // the server before the local deletion has been synced brings the line
    // back (shared multi-device orders reconcile to the server state — see
    // the "Data from other devices overrides local data" restaurant test).
    await store.data.loadServerOrders([["id", "=", order.id]]);
    expect(order.lines).toHaveLength(2);

    // But if we sync the deletion before downloading, the server no longer
    // has the line and the deletion is kept.
    order.removeOrderline(order.lines[0]);
    expect(order.lines).toHaveLength(1);
    await store.syncAllOrders({ orders: [order] });
    await store.data.loadServerOrders([["id", "=", order.id]]);
    expect(order.lines).toHaveLength(1);
});

test("edits made while the sync RPC is in flight keep their values", async () => {
    const store = await setupPosEnv();
    const order = await getFilledOrder(store);

    // Simulate a user edit landing between serialization and the server echo.
    const origCall = store.data.call.bind(store.data);
    store.data.call = async (model, method, ...rest) => {
        if (model === "pos.order" && method === "sync_from_ui") {
            order.general_customer_note = "edited mid-flight";
        }
        return origCall(model, method, ...rest);
    };

    await store.syncAllOrders({ orders: [order] });
    // The echo used to overwrite the edit's VALUE (the epoch guard only
    // preserved the dirty flag, so the next sync re-sent server values).
    expect(order.general_customer_note).toBe("edited mid-flight");
    expect(order.isDirty()).toBe(true);
});

test("a line deleted while the sync RPC is in flight is not resurrected", async () => {
    const store = await setupPosEnv();
    const order = await getFilledOrder(store);
    await store.syncAllOrders({ orders: [order] });
    expect(order.lines).toHaveLength(2);

    const origCall = store.data.call.bind(store.data);
    store.data.call = async (model, method, ...rest) => {
        if (model === "pos.order" && method === "sync_from_ui") {
            order.removeOrderline(order.lines[0]);
        }
        return origCall(model, method, ...rest);
    };
    order.general_customer_note = "force dirty";
    await store.syncAllOrders({ orders: [order], force: true });

    // The echo contained the deleted line (serialized before the deletion):
    // it must not be recreated locally while its unlink command is pending.
    expect(order.lines).toHaveLength(1);
    const serialized = order.serializeForORM({ keepCommands: true });
    expect(serialized.lines.some((cmd) => cmd[0] === 2 || cmd[0] === 3)).toBe(true);
});
