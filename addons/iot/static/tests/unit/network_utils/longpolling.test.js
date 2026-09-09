import { IoTLongpolling } from "@iot/network_utils/longpolling";
import { describe, expect, test } from "@odoo/hoot";
import { microTick } from "@odoo/hoot-mock";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";

describe.current.tags("headless");

function makeLongpolling() {
    // startPolling/stopPolling are patched out so bookkeeping tests never
    // trigger a real _poll()/fetch() cycle; the actual poll handling is
    // exercised separately below via a patched _rpcIoT.
    patchWithCleanup(IoTLongpolling.prototype, {
        startPolling: () => {},
        stopPolling: () => {},
    });
    return new IoTLongpolling({ notification: {}, orm: {} });
}

test("addListener registers every device for an iot_ip", () => {
    const iotLongpolling = makeLongpolling();

    iotLongpolling.addListener("10.0.0.5", ["d1", "d2"], "l1", () => {});

    expect(Object.keys(iotLongpolling._listeners["10.0.0.5"].devices)).toEqual([
        "d1",
        "d2",
    ]);
});

test("removeListener removes only the given device, the iot_ip entry survives", () => {
    const iotLongpolling = makeLongpolling();
    iotLongpolling.addListener("10.0.0.5", ["d1", "d2"], "l1", () => {});

    iotLongpolling.removeListener("10.0.0.5", "d1", "l1");

    expect(Object.keys(iotLongpolling._listeners["10.0.0.5"].devices)).toEqual(["d2"]);
});

test("removeListener of the last device deletes the iot_ip entry entirely", () => {
    const iotLongpolling = makeLongpolling();
    iotLongpolling.addListener("10.0.0.5", ["d1"], "l1", () => {});

    iotLongpolling.removeListener("10.0.0.5", "d1", "l1");

    expect(iotLongpolling._listeners["10.0.0.5"]).toBe(undefined);
});

test("removeListener on an iot_ip that was never registered does not throw", () => {
    const iotLongpolling = makeLongpolling();

    expect(() => iotLongpolling.removeListener("10.0.0.5", "d1")).not.toThrow();
});

test("action() no longer sets a this.protocol side effect", () => {
    const iotLongpolling = makeLongpolling();
    patchWithCleanup(iotLongpolling, {
        _rpcIoT: () => Promise.resolve({}),
    });

    iotLongpolling.action("10.0.0.5", "d1", { some: "data" });

    expect(iotLongpolling.protocol).toBe(undefined);
});

test("_poll's success handler survives its own callback removing the last device", async () => {
    const iotLongpolling = makeLongpolling();
    let called = false;
    patchWithCleanup(iotLongpolling, {
        _rpcIoT: () =>
            Promise.resolve({
                result: {
                    session_id: iotLongpolling._session_id,
                    time: 1,
                    device_identifier: "d1",
                },
            }),
    });
    iotLongpolling.addListener("10.0.0.5", ["d1"], "l1", () => {
        called = true;
        // Mirrors enterprise/iot's onMessage, which unconditionally removes
        // its own listener as the first thing it does on every message.
        iotLongpolling.removeListener("10.0.0.5", "d1", "l1");
    });

    iotLongpolling._poll("10.0.0.5");
    await microTick();
    await microTick();

    expect(called).toBe(true);
    expect(iotLongpolling._listeners["10.0.0.5"]).toBe(undefined);
});
