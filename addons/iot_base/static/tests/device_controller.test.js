import { describe, expect, test } from "@odoo/hoot";
import { DeviceController } from "@iot_base/device_controller";

describe.current.tags("headless");

function makeFakeLongpolling() {
    return {
        calls: [],
        action(iot_ip, device_identifier, data, fallback) {
            this.calls.push(["action", iot_ip, device_identifier, data, fallback]);
        },
        addListener(iot_ip, devices, listener_id, callback, fallback) {
            this.calls.push([
                "addListener",
                iot_ip,
                devices,
                listener_id,
                callback,
                fallback,
            ]);
        },
        removeListener(iot_ip, device_identifier, listener_id) {
            this.calls.push(["removeListener", iot_ip, device_identifier, listener_id]);
        },
    };
}

test("constructor maps deviceInfo onto the controller", () => {
    const iotLongpolling = makeFakeLongpolling();
    const controller = new DeviceController(iotLongpolling, {
        iot_ip: "10.0.0.5",
        identifier: "printer-1",
        iot_id: { id: 42 },
        manual_measurement: true,
    });

    expect(controller.iotIp).toBe("10.0.0.5");
    expect(controller.identifier).toBe("printer-1");
    expect(controller.iotId).toBe(42);
    expect(controller.manual_measurement).toBe(true);
    expect(controller.iotLongpolling).toBe(iotLongpolling);
});

test("iotId is undefined when iot_id is not provided", () => {
    const controller = new DeviceController(makeFakeLongpolling(), {
        iot_ip: "10.0.0.5",
        identifier: "printer-1",
    });

    expect(controller.iotId).toBe(undefined);
});

test("action() delegates to iotLongpolling.action with the controller's own ip/identifier", () => {
    const iotLongpolling = makeFakeLongpolling();
    const controller = new DeviceController(iotLongpolling, {
        iot_ip: "10.0.0.5",
        identifier: "printer-1",
    });

    controller.action({ some: "data" }, true);

    expect(iotLongpolling.calls).toEqual([
        ["action", "10.0.0.5", "printer-1", { some: "data" }, true],
    ]);
});

test("addListener() delegates with the controller's own id as listener_id", () => {
    const iotLongpolling = makeFakeLongpolling();
    const controller = new DeviceController(iotLongpolling, {
        iot_ip: "10.0.0.5",
        identifier: "printer-1",
    });
    const callback = () => {};

    controller.addListener(callback, false);

    expect(iotLongpolling.calls).toEqual([
        ["addListener", "10.0.0.5", ["printer-1"], controller.id, callback, false],
    ]);
});

test("removeListener() delegates with the controller's own ip/identifier/id", () => {
    const iotLongpolling = makeFakeLongpolling();
    const controller = new DeviceController(iotLongpolling, {
        iot_ip: "10.0.0.5",
        identifier: "printer-1",
    });

    controller.removeListener();

    expect(iotLongpolling.calls).toEqual([
        ["removeListener", "10.0.0.5", "printer-1", controller.id],
    ]);
});
