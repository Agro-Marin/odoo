import { expect, test } from "@odoo/hoot";
import DeviceIdentifierSequence from "@point_of_sale/app/utils/devices_identifier_sequence";

import { definePosModels } from "../data/generate_model_definitions.js";
import { getFilledOrder, setupPosEnv } from "../utils.js";

definePosModels();

test("Check GAP", async () => {
    const store = await setupPosEnv();
    const device = store.device;
    let orderStack = [];

    await store.deleteOrders(store.models["pos.order"].getAll());

    const createNewOrdersAndCheck = async (nbr) => {
        for (let i = 0; i < nbr; i++) {
            const order = await getFilledOrder(store);
            orderStack.push(order);
        }
    };

    const deleteOrdersAndCheck = async () => {
        const numbers = orderStack.map((order) =>
            parseInt(order.pos_reference.split("-")[2]),
        );
        await store.deleteOrders(orderStack);
        orderStack = [];
        expect(device.data.unsynced_number_stack).not.toBeEmpty();
        expect(device.data.unsynced_number_stack).toMatch(numbers);
    };

    await createNewOrdersAndCheck(15);
    expect(device.data.next_number).toBe(16);
    expect(device.data.unsynced_number_stack).toBeEmpty();

    await deleteOrdersAndCheck();

    await createNewOrdersAndCheck(15);

    expect(device.data.unsynced_number_stack).toBeEmpty();
    expect(device.data.next_number).toBe(16);
    await deleteOrdersAndCheck();
    expect(device.data.next_number).toBe(16);

    await createNewOrdersAndCheck(15);
    expect(device.data.next_number).toBe(16);

    const orders = await store.syncAllOrders();
    await store.deleteOrders(orders);

    await createNewOrdersAndCheck(15);
    expect(device.data.next_number).toBe(31);
});

test("Device identifier is set", async () => {
    const store = await setupPosEnv();
    const device = store.device;
    expect(device.identifier).not.toBeEmpty();
});

test("survives its localStorage entry disappearing mid-session", async () => {
    const store = await setupPosEnv();
    const device = store.device;
    const identifier = device.identifier;
    expect(identifier === undefined || identifier === null || identifier === "").toBe(
        false,
    );

    localStorage.removeItem(DeviceIdentifierSequence.uniqueDeviceIdentifierKey);

    expect(device.data).not.toBe(null);
    expect(device.identifier).toBe(identifier);
    expect(device.unsyncedNumberStack).toEqual([]);
    expect(device.nextNumber).toBe(1);
    expect(() => store.getSyncAllOrdersContext([])).not.toThrow();
});

test("survives a corrupt localStorage entry", async () => {
    const store = await setupPosEnv();
    const device = store.device;

    localStorage.setItem(
        DeviceIdentifierSequence.uniqueDeviceIdentifierKey,
        "{not json",
    );

    expect(device.data).not.toBe(null);
    expect(() => device.identifier).not.toThrow();
    expect(device.nextNumber).toBe(1);
});
