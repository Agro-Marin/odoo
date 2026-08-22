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

    await store.data.loadServerOrders([["id", "=", order.id]]);
    expect(order.lines).toHaveLength(2);

    order.removeOrderline(order.lines[0]);
    expect(order.lines).toHaveLength(1);
    await store.syncAllOrders({ orders: [order] });
    await store.data.loadServerOrders([["id", "=", order.id]]);
    expect(order.lines).toHaveLength(1);
});

test("edits made while the sync RPC is in flight keep their values", async () => {
    const store = await setupPosEnv();
    const order = await getFilledOrder(store);

    const origCall = store.data.call.bind(store.data);
    store.data.call = async (model, method, ...rest) => {
        if (model === "pos.order" && method === "sync_from_ui") {
            order.general_customer_note = "edited mid-flight";
        }
        return origCall(model, method, ...rest);
    };

    await store.syncAllOrders({ orders: [order] });
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

    expect(order.lines).toHaveLength(1);
    const serialized = order.serializeForORM({ keepCommands: true });
    expect(serialized.lines.some((cmd) => cmd[0] === 2 || cmd[0] === 3)).toBe(true);
});
