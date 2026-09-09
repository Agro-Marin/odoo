/** @odoo-module native */
import { formatEndpoint } from "@iot/network_utils/http";
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets";

export class IoTBoxDownloadLogs extends Component {
    static template = `iot.HeaderButton`;
    static props = {
        ...standardWidgetProps,
        btn_name: { type: String },
        btn_class: { type: String },
    };

    setup() {
        super.setup();
        this.notification = useService("notification");
        this.http = useService("http");
    }
    get ip_url() {
        return formatEndpoint(this.props.record.data.ip, "");
    }
    get name() {
        return this.props.record.data.name;
    }
    async onClick() {
        try {
            const response = await this.http.get(
                this.ip_url + "/hw_proxy/hello",
                "text",
            );
            if (response === "ping") {
                window.location = this.ip_url + "/iot_drivers/download_logs";
            } else {
                this.doWarnFail();
            }
        } catch {
            this.doWarnFail();
        }
    }
    doWarnFail() {
        this.notification.add(_t("Failed to download logs from %s", this.name), {
            type: "danger",
        });
    }
}

export const ioTBoxDownloadLogs = {
    component: IoTBoxDownloadLogs,
    extractProps: ({ attrs }) => ({
        btn_name: attrs.btn_name,
        btn_class: attrs.btn_class,
    }),
};
registry.category("view_widgets").add("iot_download_logs", ioTBoxDownloadLogs);
