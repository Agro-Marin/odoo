/** @odoo-module native */
import { Component, useState } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
const log = makeLogger("pos.navbar.proxy_status");
export class ProxyStatus extends Component {
    static template = "point_of_sale.ProxyStatus";
    static props = {};

    setup() {
        useLifecycleLog(log);
        this.pos = usePos();
        this.ui = useService("ui");
        const hardwareProxy = useService("hardware_proxy");
        this.connectionInfo = useState(hardwareProxy.connectionInfo);
    }

    get message() {
        if (this.connectionInfo.status === "connected") {
            const { drivers } = this.connectionInfo;
            const {
                iface_scan_via_proxy,
                iface_print_via_proxy,
                iface_cashdrawer,
                iface_electronic_scale,
            } = this.pos.config;
            const devices = [
                {
                    name: _t("Scanner"),
                    driver: drivers.scanner,
                    enabled: iface_scan_via_proxy,
                },
                {
                    name: _t("Printer"),
                    driver: drivers.printer,
                    enabled: iface_print_via_proxy || iface_cashdrawer,
                },
                {
                    name: _t("Scale"),
                    driver: drivers.scale,
                    enabled: iface_electronic_scale,
                },
            ];
            const disconnectedDevices = devices.filter(
                ({ enabled, driver }) =>
                    enabled && !["connected", "connecting"].includes(driver?.status),
            );
            log.logic("message: device status", () => ({
                devices: devices.map((d) => ({
                    name: d.name,
                    enabled: Boolean(d.enabled),
                    status: d.driver?.status,
                })),
                disconnected: disconnectedDevices.map((d) => d.name),
            }));
            if (disconnectedDevices.length) {
                return `${disconnectedDevices.map((d) => d.name).join(" & ")} ${_t("Offline")}`;
            }
            return "";
        }
        return this.connectionInfo.message || "";
    }
}
