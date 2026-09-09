/** @odoo-module native */
import { readDeviceEvent } from "@iot/device_messages";
import { printReport } from "@iot/iot_report_action";
import { useSubEnv } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { formView } from "@web/views/form";

class IoTDeviceController extends formView.Controller {
    setup() {
        super.setup();
        this.iotHttp = useService("iot_http");
        this.notification = useService("notification");
        this.orm = useService("orm");

        useSubEnv({ onClickViewButton: this.onClickButtonTest.bind(this) });
    }

    async onRecordSaved(record) {
        if (["keyboard", "scanner"].includes(record.data.type)) {
            await this.updateKeyboardLayout(record.data);
        } else if (record.data.type === "display") {
            await this.updateDisplayUrl(record.data);
        }
    }
    /**
     * Send an action to the device to update the keyboard layout
     */
    async updateKeyboardLayout(data) {
        const { iot_id, identifier, keyboard_layout, is_scanner } = data;
        // IMPROVEMENT: Perhaps combine the call to update_is_scanner and update_layout in just one remote call to the iotbox.
        this.iotHttp.action(
            iot_id.id,
            identifier,
            {
                action: "update_is_scanner",
                is_scanner,
            },
            () => {},
            () => {
                this.notification.add(
                    _t("Failed to update scanner mode on the device."),
                    {
                        type: "danger",
                    },
                );
            },
        );
        if (keyboard_layout) {
            const [keyboard] = await this.model.orm.read(
                "iot.keyboard.layout",
                [keyboard_layout.id],
                ["layout", "variant"],
            );
            return this.iotHttp.action(
                iot_id.id,
                identifier,
                {
                    action: "update_layout",
                    layout: keyboard.layout,
                    variant: keyboard.variant,
                },
                () => {},
                () => {
                    this.notification.add(
                        _t("Failed to update keyboard layout on the device."),
                        {
                            type: "danger",
                        },
                    );
                },
            );
        } else {
            return this.iotHttp.action(iot_id.id, identifier, {
                action: "update_layout",
            });
        }
    }
    /**
     * Send an action to the device to update the screen url
     */
    async updateDisplayUrl(data) {
        const { iot_id, identifier, display_url } = data;
        return this.iotHttp.action(iot_id.id, identifier, {
            action: "update_url",
            url: display_url,
        });
    }

    onDeviceEvent(event, type) {
        const { message: errorMessage, defaultMessage } = readDeviceEvent(
            type,
            event,
        );
        switch (event.status) {
            case "error":
            case "timeout":
                this.notification.add(errorMessage, { type: "danger" });
                return;
            case "warning":
                this.notification.add(errorMessage, { type: "warning" });
                return;
            case "disconnected":
                this.notification.add(_t("Device is disconnected"), { type: "danger" });
                return;
            default:
                this.notification.add(defaultMessage, { type: "info" });
                return;
        }
    }

    async onClickButtonTest(params) {
        if (params.clickParams.name === "test_device") {
            const { iot_id, identifier, type, subtype } = this.model.root.data;

            if (type === "printer" && subtype === "office_printer") {
                // We print a "real" pdf report: the external report sample
                const reportId = (
                    await this.orm.searchRead(
                        "ir.actions.report",
                        [
                            ["report_type", "=", "qweb-pdf"],
                            ["report_name", "=", "web.preview_externalreport"],
                        ],
                        ["id"],
                        { limit: 1 },
                    )
                )[0].id;
                const deviceId = this.model.root.resId;
                return printReport(this.env, [reportId, [deviceId], null], [deviceId]);
            }

            return this.iotHttp.action(
                iot_id.id,
                identifier,
                { action: "status" },
                (event) => this.onDeviceEvent(event, type),
                (event) => this.onDeviceEvent(event, type),
            );
        }
    }
}

export const iotDeviceFormView = {
    ...formView,
    Controller: IoTDeviceController,
};

registry.category("views").add("iot_device_form", iotDeviceFormView);
