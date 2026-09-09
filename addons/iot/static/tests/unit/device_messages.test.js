import { deviceMessages, readDeviceEvent } from "@iot/device_messages";
import { describe, expect, test } from "@odoo/hoot";

describe.current.tags("headless");

test("a printer event is read through the table the base app ships", () => {
    const { message, defaultMessage } = readDeviceEvent("printer", {
        status: "error",
        message: "ERROR_NO_PAPER",
    });
    expect(message.toString()).toBe("Out of paper");
    expect(defaultMessage.toString()).toBe("Test page printed");
});

test("an unknown message code is reported as it arrived", () => {
    const { message } = readDeviceEvent("printer", {
        status: "error",
        message: "ERROR_FROM_A_FUTURE_FIRMWARE",
    });
    expect(message).toBe("ERROR_FROM_A_FUTURE_FIRMWARE");
});

test("a device type nobody registered still reads", () => {
    const { message, defaultMessage } = readDeviceEvent("scale", {
        status: "success",
        message: undefined,
    });
    expect(message).toBe(undefined);
    expect(defaultMessage.toString()).toBe("Device is operational");
});

test("normalize may turn an apparent success into the failure it really is", () => {
    // The seam a fiscal data module needs: it reports failure in the body
    // rather than in `status`, so the event has to be rewritten before anything
    // reads it. Registered here rather than depending on a driver module.
    deviceMessages.add("test.device", {
        messages: { 201: "Card broken" },
        defaultMessage: "All good",
        normalize(event) {
            const code = event.result?.error?.errorCode?.substring(0, 3);
            if (code && code !== "000") {
                event.message = code;
                event.status = "error";
            }
        },
    });

    const event = { status: "success", result: { error: { errorCode: "201x" } } };
    const { message } = readDeviceEvent("test.device", event);
    expect(event.status).toBe("error");
    expect(message).toBe("Card broken");

    const ok = { status: "success", result: { error: { errorCode: "000" } } };
    readDeviceEvent("test.device", ok);
    expect(ok.status).toBe("success");
});
