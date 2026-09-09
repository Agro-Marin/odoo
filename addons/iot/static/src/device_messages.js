/** @odoo-module native */
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";

/**
 * How to read the events a device type sends back, keyed by `iot.device.type`.
 *
 * A module that teaches the IoT Box about a device registers an entry here
 * rather than editing the device form, so the base app carries no vendor's
 * error codes. An entry may provide:
 *
 *   messages        error code -> human readable string
 *   defaultMessage  what a successful test reports
 *   normalize       rewrite an event before anything reads it, for a device
 *                   that reports failure somewhere other than `status`
 *
 * Registrants reach the category by name rather than importing this module, so
 * a driver module stays a leaf that any bundle can carry on its own.
 */
export const deviceMessages = registry.category("iot_device_messages");

export const PRINTER_MESSAGES = {
    ERROR_FAILED: _t("Failed to initiate print"),
    ERROR_OFFLINE: _t("Printer is not ready"),
    ERROR_TIMEOUT: _t("Printing timed out"),
    ERROR_NO_PAPER: _t("Out of paper"),
    ERROR_UNREACHABLE: _t("Printer is unreachable"),
    ERROR_UNKNOWN: _t("Unknown printer error occurred"),
    WARNING_LOW_PAPER: _t("Paper is low"),
};

deviceMessages.add("printer", {
    messages: PRINTER_MESSAGES,
    defaultMessage: _t("Test page printed"),
});

/**
 * Read one device event through whatever its type registered.
 *
 * `normalize` runs first and may rewrite the event, so a device that reports
 * failure somewhere other than `status` is read the same way as one that does
 * not. A type nobody registered still reads, which is what keeps an unknown
 * device from throwing in the form.
 *
 * @param {string} type an `iot.device.type` value
 * @param {{status?: string, message?: string}} event mutated by `normalize`
 * @returns {{message: string, defaultMessage: string}}
 */
export function readDeviceEvent(type, event) {
    const spec = deviceMessages.get(type, {});
    spec.normalize?.(event);
    return {
        message: spec.messages?.[event.message] ?? event.message,
        defaultMessage: spec.defaultMessage ?? _t("Device is operational"),
    };
}
