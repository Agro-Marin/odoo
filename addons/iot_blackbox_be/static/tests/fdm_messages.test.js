import "@iot_blackbox_be/fdm_messages";

import { readDeviceEvent } from "@iot/device_messages";
import { describe, expect, test } from "@odoo/hoot";

describe.current.tags("headless");

test("an error code buried in the response body becomes an error status", () => {
    // The blackbox answers 200 with the failure inside the body, so an event
    // that reads as a success has to be re-read before anything acts on it.
    const event = { status: "success", result: { error: { errorCode: "204" } } };
    const { message } = readDeviceEvent("fiscal_data_module", event);
    expect(event.status).toBe("error");
    expect(message.toString()).toBe("Invalid PIN.");
});

test("operational and repeated-request are not failures", () => {
    for (const code of ["000", "102"]) {
        const event = { status: "success", message: code };
        readDeviceEvent("fiscal_data_module", event);
        expect(event.status).toBe("success");
    }
});

test("a code the table does not know is left alone", () => {
    const event = { status: "success", message: "999" };
    const { message } = readDeviceEvent("fiscal_data_module", event);
    expect(event.status).toBe("success");
    expect(message).toBe("999");
});
