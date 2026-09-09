/** @odoo-module native */
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";

export const FDM_MESSAGES = {
    "000": _t("Blackbox is running and operational"),
    "001": _t("PIN accepted."),
    101: _t("Fiscal Data Module memory 90% full."),
    102: _t(
        "Repeated request. This request was already handled by the fiscal data module.",
    ),
    103: _t("Operation wasn't saved on the blackbox"),
    199: _t("Unspecified warning."),
    201: _t("No Vat Signing Card or Vat Signing Card broken."),
    202: _t("Please activate the Vat Signing Card with PIN."),
    203: _t("Vat Signing Card blocked."),
    204: _t("Invalid PIN."),
    205: _t("Fiscal Data Module memory full."),
    206: _t("Unknown identifier."),
    207: _t("Invalid data in message sent to the blackbox."),
    208: _t("Fiscal Data Module not operational. Please restart the blackbox"),
    209: _t("Fiscal Data Module real time clock corrupt."),
    210: _t("Vat Signing Card not compatible with Fiscal Data Module."),
    299: _t("Unspecified error."),
    300: _t(
        "Blackbox responded with invalid response. Please check the cable connection and the power supply, then retry. Restart if necessary",
    ),
    301: _t(
        "Blackbox did not respond to your request. This usually means it has disconnected. Please check its cable connection and its power supply. Restart if necessary.",
    ),
    426: _t(
        "Blackbox driver update required. Please restart your IoT Box to update the blackbox driver.",
    ),
};

registry.category("iot_device_messages").add("fiscal_data_module", {
    messages: FDM_MESSAGES,
    defaultMessage: _t("Fiscal Data Module is connected and operational"),

    /**
     * The blackbox reports a failure in its response body rather than in
     * `status`, so an event that reads as a success has to be re-read before
     * anything acts on it. "000" is operational and "102" is a repeat of a
     * request it already handled, so neither is an error.
     */
    normalize(event) {
        const fullErrorCode = event.message ?? event.result?.error?.errorCode;
        const errorCode = fullErrorCode?.substring(0, 3);
        if (FDM_MESSAGES[errorCode] && !["000", "102"].includes(errorCode)) {
            event.message = errorCode;
            event.status = "error";
        }
    },
});
