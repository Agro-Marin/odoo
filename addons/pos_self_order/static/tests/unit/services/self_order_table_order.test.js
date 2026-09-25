import { expect, test } from "@odoo/hoot";
import { uuidv4 } from "@point_of_sale/utils";
import {
    Command,
    MockServer,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";

import { definePosSelfModels } from "../data/generate_model_definitions.js";
import { getFilledSelfOrder, setupSelfPosEnv } from "../utils.js";

definePosSelfModels();

const serveTableOrder = (productId) => {
    const ids = [];
    onRpc("/pos-self-order/get-user-data/", () => {
        const orderId = MockServer.env["pos.order"].create({
            uuid: uuidv4(),
            access_token: uuidv4(),
            state: "draft",
            session_id: 1,
            config_id: 1,
            lines: [
                Command.create({
                    uuid: uuidv4(),
                    product_id: productId,
                    qty: 1,
                    price_unit: 3,
                }),
            ],
        });
        ids.push(orderId);
        const data = MockServer.env["pos.order"].read_pos_data([orderId], [], 1);
        const models = MockServer.env["pos.session"]._load_self_data_models();
        return Object.fromEntries(
            Object.entries(data).filter(([model]) => models.includes(model)),
        );
    });
    return ids;
};

test("the table's order arriving takes the unsent cart's lines in", async () => {
    const store = await setupSelfPosEnv("mobile", "table", "meal");
    patchWithCleanup(store.router, { getTableIdentifier: () => "T1" });
    const cart = await getFilledSelfOrder(store);
    const cartLineUuids = cart.lines.map((line) => line.uuid);
    expect(cart.isSynced).toBe(false);
    const served = serveTableOrder(cart.lines[0].product_id.id);

    await store.getUserDataFromServer();

    const tableOrder = store.models["pos.order"].get(served[0]);
    expect(store.currentOrder.uuid).toBe(tableOrder.uuid);
    expect(tableOrder.lines).toHaveLength(3);
    for (const uuid of cartLineUuids) {
        expect(tableOrder.lines.map((line) => line.uuid)).toInclude(uuid);
    }
    expect(store.models["pos.order"].some((order) => order.uuid === cart.uuid)).toBe(
        false,
    );
});

test("the table's order arriving leaves the device's sent orders alone", async () => {
    const store = await setupSelfPosEnv("mobile", "table", "meal");
    patchWithCleanup(store.router, { getTableIdentifier: () => "T1" });
    await getFilledSelfOrder(store);
    const sent = await store.sendDraftOrderToServer();
    expect(sent.isSynced).toBe(true);
    const sentLineUuids = sent.lines.map((line) => line.uuid);

    const cart = store.createNewOrder();
    store.selectedOrderUuid = cart.uuid;
    await store.addToCart(store.models["product.template"].get(5), 1);
    const [cartLine] = cart.lines;
    const served = serveTableOrder(cartLine.product_id.id);

    await store.getUserDataFromServer();

    const tableOrder = store.models["pos.order"].get(served[0]);
    expect(store.currentOrder.uuid).toBe(tableOrder.uuid);
    expect(tableOrder.lines.map((line) => line.uuid)).toInclude(cartLine.uuid);
    const kept = store.models["pos.order"].get(sent.id);
    expect(kept?.uuid).toBe(sent.uuid);
    expect(kept?.lines.map((line) => line.uuid)).toEqual(sentLineUuids);
});
